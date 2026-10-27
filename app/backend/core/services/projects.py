"""项目创建（深拷贝模板，AC-F01-01、AC-F03-01）与工序说明库匹配（AC-F03-10）。"""
import datetime
import json
import re
from pathlib import Path

from django.db import transaction

from core.models import (ArchiveFolder, Baseline, Company, Floor, Phase, ProcessRule, Project, Room, Template,
                         WorkItem)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "jh_template.json"
PHASE_COLORS = ["--phase-1", "--phase-2", "--phase-3", "--phase-4", "--phase-5", "--phase-6"]
ARCHIVE_DEFAULTS = {
    "layout": ["负一楼", "夹层", "一楼", "二楼", "三楼", "楼顶阳台"],
    "render": ["负一楼", "夹层", "一楼", "二楼", "三楼", "楼顶阳台"],
    "contract": ["主合同", "补充协议", "报价与变更", "付款凭证"],
}


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def ensure_company_template(company):
    """首次启动时把君华模板与工序规则装入公司（可重复调用）。"""
    tpl = Template.objects.filter(company=company).first()
    if tpl is None:
        data = load_fixture()
        tpl = Template.objects.create(company=company, name="君华别墅模板",
                                      content={k: data[k] for k in ("floors", "rooms", "phases")})
    if not ProcessRule.objects.filter(company=company).exists():
        for r in load_fixture()["rules"]:
            ProcessRule.objects.create(company=company, order_no=r["order"], keywords=r["pattern"].split("|"),
                                       work_description=r["description"], acceptance_criteria=r["criteria"])
    return tpl


def match_rule(company_id, name):
    """按 order_no 取首个命中规则：名称命中任一关键词（关键词可含 .* 表示「先后包含」）。"""
    for rule in ProcessRule.objects.filter(company_id=company_id, is_active=True).order_by("order_no", "id"):
        for k in rule.keywords:
            try:
                if re.search(k, name):
                    return rule
            except re.error:
                if k in name:
                    return rule
    return None


def apply_rule(work_item):
    """未填写的工作说明 / 验收标准按规则补齐，已填写的不覆盖。"""
    if work_item.description and work_item.acceptance_criteria:
        return work_item
    rule = match_rule(work_item.project.company_id, work_item.name)
    if rule:
        if not work_item.description:
            work_item.description = rule.work_description
        if not work_item.acceptance_criteria:
            work_item.acceptance_criteria = rule.acceptance_criteria
    return work_item


def _date_in_year(md, start, end):
    """原型只给月日：取落在工段起止之间（或最接近）的年份。"""
    m, dd = (int(x) for x in md.split("-"))
    for y in (start.year, end.year):
        try:
            cand = datetime.date(y, m, dd)
        except ValueError:
            continue
        if start <= cand <= end:
            return cand
    return datetime.date(start.year, m, dd)


@transaction.atomic
def create_from_template(company, template, name, address, planned_start, planned_handover, user):
    """深拷贝模板到项目表，不保留引用（改模板不影响已建项目）。"""
    project = Project.objects.create(company=company, template=template, name=name, address=address,
                                     planned_start=planned_start, planned_handover=planned_handover)
    content = template.content
    floors = {}
    for f in content["floors"]:
        floors[f["code"]] = Floor.objects.create(project=project, code=f["code"], name=f["name"], order_no=f["order"])
    rooms = {}
    for r in content["rooms"]:
        rooms[r["code"]] = Room.objects.create(project=project, floor=floors[r["floor"]], code=r["code"],
                                               name=r["name"], order_no=r["order"])
    shift = (planned_start - datetime.date.fromisoformat(content["phases"][0]["start"])).days if content["phases"] else 0
    for i, p in enumerate(content["phases"]):
        ps = datetime.date.fromisoformat(p["start"]) + datetime.timedelta(days=shift)
        pe = datetime.date.fromisoformat(p["end"]) + datetime.timedelta(days=shift)
        phase = Phase.objects.create(project=project, code=p["code"], name=p["name"], color_var=PHASE_COLORS[i % 6],
                                     order_no=p["order"], planned_start=ps, planned_end=pe, team_lead=p.get("team", ""),
                                     weight=p.get("weight", 10), scope_note=p.get("scope", ""))
        tpl_start, tpl_end = datetime.date.fromisoformat(p["start"]), datetime.date.fromisoformat(p["end"])
        for t in p["tasks"]:
            plan = None
            if t.get("plan"):
                plan = _date_in_year(t["plan"], tpl_start, tpl_end) + datetime.timedelta(days=shift)
            wi = WorkItem(project=project, phase=phase, floor=floors.get(t.get("floor")), room=rooms.get(t.get("room")),
                          name=t["name"], planned_finish=plan, owner_name=t.get("owner", ""), weight=t.get("weight", 1),
                          description=t.get("description", ""), acceptance_criteria=t.get("criteria", ""),
                          checkpoint_hints=t.get("checkpoints", []))
            apply_rule(wi)  # 只补齐模板未填的说明与标准
            wi.save()
            Baseline.objects.create(project=project, work_item=wi)
    for zone, names in ARCHIVE_DEFAULTS.items():
        for i, n in enumerate(names):
            ArchiveFolder.objects.create(project=project, zone=zone, name=n, order_no=i)
    return project


def default_company():
    return Company.objects.order_by("id").first() or Company.objects.create(name="君华建装")
