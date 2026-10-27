"""公司模板与工序说明库（API-F03-01，REQ-F03-01、REQ-F03-05）。

只有公司管理员可读写。模板保存在 Template.content（工段含工作项与检查点模板、楼层、房间），
建项目时由 services.projects.create_from_template 深拷贝，所以保存模板不影响已建项目（AC-F03-01）。
工序说明库是公司级规则（ProcessRule），按顺序首个命中补齐（AC-F03-10）。
"""
import copy
import datetime

from django.db import transaction
from django.urls import path
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.base import iso
from core.errors import fail, forbidden, validation
from core.models import AuditLog, ProcessRule, Project, Template
from core.services import audit
from core.services.projects import default_company, ensure_company_template

ADMIN_ONLY = "仅公司管理员可访问公司管理页面"


def _admin(request):
    if not request.user.is_company_admin:
        forbidden(ADMIN_ONLY)
    company = default_company()
    ensure_company_template(company)
    return company


def rule_dict(r):
    return {"id": r.id, "order": r.order_no, "keywords": r.keywords, "description": r.work_description,
            "criteria": r.acceptance_criteria}


def _rules(company):
    return ProcessRule.objects.filter(company=company, is_active=True).order_by("order_no", "id")


def _last_saved(t):
    a = (AuditLog.objects.filter(object_type="template", object_id=str(t.id), action__in=["template.save", "template.create"])
         .select_related("actor").order_by("-at", "-id").first())
    return {"at": iso(a.at), "by": a.actor.name if a.actor else "系统"} if a else None


def template_summary(t, rule_count):
    c = t.content or {}
    phases = c.get("phases", [])
    return {"id": t.id, "name": t.name, "updatedAt": iso(t.updated_at), "lastSaved": _last_saved(t),
            "stats": {"phases": len(phases), "floors": len(c.get("floors", [])), "rooms": len(c.get("rooms", [])),
                      "workItems": sum(len(p.get("tasks", [])) for p in phases), "rules": rule_count}}


def _int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def normalize_content(raw):
    """校验并规范化模板内容；一次返回全部字段错误。保留建项目需要的 code / order / start / end。"""
    errs = []
    floors_in = raw.get("floors") or []
    rooms_in = raw.get("rooms") or []
    phases_in = raw.get("phases") or []

    floors, floor_codes = [], set()
    for i, f in enumerate(floors_in):
        name = str(f.get("name", "")).strip()
        if not name:
            errs.append((f"floors.{i}.name", "请填写楼层名称"))
        code = str(f.get("code") or "").strip()
        if not code or code in floor_codes:
            n = len(floor_codes) + 1
            while f"f{n}" in floor_codes:
                n += 1
            code = f"f{n}"
        floor_codes.add(code)
        floors.append({"code": code, "name": name, "order": i})

    rooms, room_codes = [], set()
    for i, r in enumerate(rooms_in):
        name = str(r.get("name", "")).strip()
        floor = r.get("floor")
        if not name:
            errs.append((f"rooms.{i}.name", "请填写房间名称"))
        if floor not in floor_codes:
            errs.append((f"rooms.{i}.floor", "请选择楼层"))
        code = str(r.get("code") or "").strip()
        if not code or code in room_codes:
            n = 1
            while f"{floor}-r{n}" in room_codes:
                n += 1
            code = f"{floor}-r{n}"
        room_codes.add(code)
        rooms.append({"code": code, "floor": floor, "name": name, "order": i})
    room_floor = {r["code"]: r["floor"] for r in rooms}

    if not phases_in:
        errs.append(("phases", "请至少保留一个工段"))
    phases, names, phase_codes = [], set(), set()
    total = 0
    prev_end = None
    for i, p in enumerate(phases_in):
        name = str(p.get("name", "")).strip()
        if not name:
            errs.append((f"phases.{i}.name", "请填写工段名称"))
        elif name in names:
            errs.append((f"phases.{i}.name", "工段名称重复"))
        names.add(name)
        weight = _int(p.get("weight"))
        if weight is None or weight < 0 or weight > 100:
            errs.append((f"phases.{i}.weight", "权重为 0–100 的整数"))
            weight = 0
        total += weight
        code = str(p.get("code") or "").strip()
        if not code or code in phase_codes:
            n = len(phase_codes) + 1
            while f"p{n}" in phase_codes:
                n += 1
            code = f"p{n}"
        phase_codes.add(code)
        try:
            start = datetime.date.fromisoformat(str(p.get("start")))
            end = datetime.date.fromisoformat(str(p.get("end")))
        except ValueError:
            start = (prev_end + datetime.timedelta(days=1)) if prev_end else datetime.date(2026, 9, 19)
            end = start + datetime.timedelta(days=29)
        prev_end = end
        tasks = []
        for j, t in enumerate(p.get("tasks") or []):
            tname = str(t.get("name", "")).strip()
            key = f"phases.{i}.tasks.{j}"
            if not tname:
                errs.append((f"{key}.name", "请填写工作项名称"))
            floor = t.get("floor") or None
            room = t.get("room") or None
            if floor is not None and floor not in floor_codes:
                errs.append((f"{key}.floor", "请选择楼层"))
            if room is not None and room_floor.get(room) != floor:
                errs.append((f"{key}.room", "房间与楼层不匹配"))
            tw = _int(t.get("weight"), 1)
            if not 1 <= tw <= 5:
                errs.append((f"{key}.weight", "权重为 1–5 的整数"))
            cps = []
            for c in t.get("checkpoints") or []:
                point = str(c.get("point", "")).strip()
                if not point:
                    errs.append((f"{key}.checkpoints", "请填写检查要点，或删除空的检查点模板"))
                cps.append({"point": point, "isConcealed": bool(c.get("isConcealed", True))})
            task = {"name": tname, "plan": t.get("plan"), "owner": str(t.get("owner") or ""), "weight": tw,
                    "floor": floor, "room": room}
            if str(t.get("description") or "").strip():
                task["description"] = str(t["description"]).strip()
            if str(t.get("criteria") or "").strip():
                task["criteria"] = str(t["criteria"]).strip()
            if cps:
                task["checkpoints"] = cps
            tasks.append(task)
        phases.append({"code": code, "name": name, "start": start.isoformat(), "end": end.isoformat(),
                       "team": str(p.get("team") or ""), "weight": weight, "scope": str(p.get("scope") or ""),
                       "order": i, "tasks": tasks})
    if phases_in and total != 100:
        errs.append(("phases", f"工段权重合计为 {total}%，需为 100%"))
    validation(errs)
    return {"floors": floors, "rooms": rooms, "phases": phases}


def normalize_rules(raw):
    errs, out = [], []
    for i, r in enumerate(raw):
        kws = r.get("keywords") or []
        if isinstance(kws, str):
            kws = kws.replace("，", "、").replace(",", "、").split("、")
        kws = [str(k).strip() for k in kws if str(k).strip()]
        desc = str(r.get("description", "")).strip()
        crit = str(r.get("criteria", "")).strip()
        if not kws:
            errs.append((f"rules.{i}.keywords", "请填写匹配关键词"))
        if not desc:
            errs.append((f"rules.{i}.description", "请填写工作说明"))
        if not crit:
            errs.append((f"rules.{i}.criteria", "请填写验收标准"))
        out.append({"id": _int(r.get("id")), "keywords": kws, "description": desc, "criteria": crit})
    validation(errs)
    return out


def save_rules(company, rules, actor):
    """整表保存：顺序即列表顺序；未出现的旧规则停用（不物理删除，保留可追溯）。"""
    existing = {r.id: r for r in ProcessRule.objects.select_for_update().filter(company=company, is_active=True)}
    keep = set()
    for i, r in enumerate(rules, start=1):
        obj = existing.get(r["id"])
        if obj is None:
            obj = ProcessRule(company=company)
        obj.order_no, obj.keywords = i, r["keywords"]
        obj.work_description, obj.acceptance_criteria, obj.is_active = r["description"], r["criteria"], True
        obj.save()
        keep.add(obj.id)
    removed = [rid for rid in existing if rid not in keep]
    if removed:
        ProcessRule.objects.filter(pk__in=removed).update(is_active=False)
    audit.log(actor, "process_rules.save", "process_rule", "", f"工序说明库 {len(rules)} 条",
              None, {"count": len(rules), "removed": len(removed)})


class AdminTemplates(APIView):
    def get(self, request):
        company = _admin(request)
        n = _rules(company).count()
        return Response({"items": [template_summary(t, n) for t in Template.objects.filter(company=company).order_by("id")],
                         "projectCount": Project.objects.filter(company=company).count()})

    def post(self, request):
        """新建模板：可从已有模板复制（copyFromId）。"""
        company = _admin(request)
        name = str(request.data.get("name", "")).strip()
        if not name:
            validation([("name", "请填写模板名称")])
        if Template.objects.filter(company=company, name=name).exists():
            validation([("name", "模板名称重复")])
        src = Template.objects.filter(company=company, pk=request.data.get("copyFromId")).first()
        content = copy.deepcopy(src.content) if src else {"floors": [], "rooms": [], "phases": []}
        t = Template.objects.create(company=company, name=name, content=content)
        audit.log(request.user, "template.create", "template", t.id, t.name, None, {"copyFrom": src.name if src else None})
        return Response(template_summary(t, _rules(company).count()), status=201)


class AdminTemplateDetail(APIView):
    def _get(self, request, tid):
        company = _admin(request)
        t = Template.objects.filter(company=company, pk=tid).first()
        if t is None:
            fail("NOT_FOUND", "模板不存在", 404)
        return company, t

    def get(self, request, tid):
        company, t = self._get(request, tid)
        return Response({**template_summary(t, _rules(company).count()), "content": t.content,
                         "rules": [rule_dict(r) for r in _rules(company)],
                         "projectCount": Project.objects.filter(company=company).count()})

    def put(self, request, tid):
        """保存模板（含工序说明库）。只改模板本身，已建项目不受影响（AC-F03-01）。"""
        company, t = self._get(request, tid)
        name = str(request.data.get("name", t.name)).strip()
        errs = []
        if not name:
            errs.append(("name", "请填写模板名称"))
        elif Template.objects.filter(company=company, name=name).exclude(pk=t.pk).exists():
            errs.append(("name", "模板名称重复"))
        validation(errs)
        content = normalize_content(request.data.get("content") or {})
        rules = normalize_rules(request.data["rules"]) if "rules" in request.data else None
        with transaction.atomic():
            t = Template.objects.select_for_update().get(pk=t.pk)
            before = template_summary(t, _rules(company).count())["stats"]
            t.name, t.content = name, content
            t.save()
            if rules is not None:
                save_rules(company, rules, request.user)
            after = template_summary(t, _rules(company).count())["stats"]
            audit.log(request.user, "template.save", "template", t.id, t.name, before, after)
        return self.get(request, tid)

    def patch(self, request, tid):
        return self.put(request, tid)


class AdminRules(APIView):
    def get(self, request):
        company = _admin(request)
        return Response({"items": [rule_dict(r) for r in _rules(company)]})

    def post(self, request):
        company = _admin(request)
        r = normalize_rules([request.data])[0]
        with transaction.atomic():
            last = _rules(company).order_by("-order_no").first()
            obj = ProcessRule.objects.create(company=company, order_no=(last.order_no + 1) if last else 1,
                                             keywords=r["keywords"], work_description=r["description"],
                                             acceptance_criteria=r["criteria"])
            audit.log(request.user, "process_rule.create", "process_rule", obj.id, "、".join(obj.keywords))
        return Response(rule_dict(obj), status=201)


class AdminRuleDetail(APIView):
    def patch(self, request, rid):
        company = _admin(request)
        obj = ProcessRule.objects.filter(company=company, pk=rid, is_active=True).first()
        if obj is None:
            fail("NOT_FOUND", "规则不存在", 404)
        merged = {"keywords": request.data.get("keywords", obj.keywords),
                  "description": request.data.get("description", obj.work_description),
                  "criteria": request.data.get("criteria", obj.acceptance_criteria)}
        r = normalize_rules([merged])[0]
        before = rule_dict(obj)
        obj.keywords, obj.work_description, obj.acceptance_criteria = r["keywords"], r["description"], r["criteria"]
        obj.save()
        audit.log(request.user, "process_rule.update", "process_rule", obj.id, "、".join(obj.keywords), before, rule_dict(obj))
        return Response(rule_dict(obj))

    def delete(self, request, rid):
        company = _admin(request)
        obj = ProcessRule.objects.filter(company=company, pk=rid, is_active=True).first()
        if obj is None:
            fail("NOT_FOUND", "规则不存在", 404)
        obj.is_active = False
        obj.save(update_fields=["is_active"])
        audit.log(request.user, "process_rule.disable", "process_rule", obj.id, "、".join(obj.keywords))
        return Response({"ok": True})


class AdminRuleOrder(APIView):
    def post(self, request):
        company = _admin(request)
        ids = [_int(x) for x in request.data.get("ids", [])]
        with transaction.atomic():
            rules = {r.id: r for r in ProcessRule.objects.select_for_update().filter(company=company, is_active=True)}
            if sorted(i for i in ids if i) != sorted(rules):
                validation([("ids", "规则列表已变化，请刷新后重试")])
            for i, rid in enumerate(ids, start=1):
                ProcessRule.objects.filter(pk=rid).update(order_no=i)
            audit.log(request.user, "process_rule.reorder", "process_rule", "", "工序说明库排序")
        return Response({"items": [rule_dict(r) for r in _rules(company)]})


urlpatterns = [
    path("admin/templates", AdminTemplates.as_view()),
    path("admin/templates/<int:tid>", AdminTemplateDetail.as_view()),
    path("admin/process-rules", AdminRules.as_view()),
    path("admin/process-rules/order", AdminRuleOrder.as_view()),
    path("admin/process-rules/<int:rid>", AdminRuleDetail.as_view()),
]
