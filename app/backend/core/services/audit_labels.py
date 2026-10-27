"""操作日志的中文显示（AC-F17-04：操作人、角色、时间、对象、前后值均以可读中文呈现）。

各模块写日志时用的是英文动作码与字段键，这里集中翻译，展示层不暴露内部代码。
"""
ACTIONS = {
    "create": "新增", "update": "修改", "void": "作废", "status": "状态变更", "delete": "删除",
    "acceptance_photo.status": "修改验收图片状态", "acceptance_photo.upload": "上传验收图片",
    "agent.assign": "指定代理人", "agent.revoke": "撤销代理人",
    "attachment.upload": "上传资料", "attachment.void": "作废资料",
    "attendance.batch": "批量登记出勤", "attendance.set": "登记出勤",
    "baseline.return": "退回基线", "baseline.sign": "签认基线", "baseline.submit": "提交基线",
    "change.create": "发起变更单", "change.submit": "提交变更单", "change.resubmit": "重新提交变更单",
    "change.price": "定价", "change.reject": "驳回变更单", "change.sign": "签认变更单",
    "checkpoint.check": "核对", "checkpoint.create": "新建检查点", "checkpoint.discovery_correct": "修正发现时点",
    "checkpoint.mark_covered": "标记已覆盖", "checkpoint.release": "放行",
    "drawing_set.create": "新建图纸分册", "drawing_version.create": "发布图纸版本", "drawing_version.sign": "签认图纸",
    "experience.review": "审核经验", "experience.revise": "修改经验", "experience.submit": "提交经验",
    "invitation.accept": "接受邀请", "invitation.create": "生成邀请", "invitation.revoke": "撤销邀请",
    "issue.assign": "指派问题", "issue.cause": "判定问题原因", "issue.close": "闭环问题", "issue.create": "登记问题",
    "issue.reopen": "重开问题", "issue.void": "作废问题", "issue.change_draft": "生成变更单草稿",
    "member.remove": "移除成员", "member.roles": "修改角色",
    "password.change": "修改密码", "password.reset": "重置密码",
    "phase.plan": "修改工段计划", "plan.import.execute": "执行计划导入", "plan.import.validate": "校验计划导入",
    "process_rules.save": "保存工序规则",
    "project.create": "新建项目", "project.release_timeout": "修改放行时限", "project.status": "推进项目状态",
    "prototype.import": "导入原型数据", "prototype.import.reject": "原型数据导入失败",
    "template.create": "新建模板", "template.save": "保存模板", "todo.ack": "确认知会",
    "work_item.create": "新增工作项", "work_item.update": "修改工作项", "work_item.disable": "停用工作项",
    "work_item.delete": "删除工作项", "structure.create": "新增结构", "structure.update": "修改结构",
}

OBJECT_TYPES = {
    "changeorder": "变更单", "change_order": "变更单", "issue": "问题", "checkpoint": "检查点", "checkrecord": "核对记录",
    "check_record": "核对记录", "storedfile": "资料文件", "file": "资料文件", "phase": "工段计划", "member": "成员",
    "projectmemberrole": "成员", "baseline": "基线", "drawingversion": "图纸版本", "drawing_version": "图纸版本",
    "drawing_set": "图纸分册", "workitem": "工作项", "work_item": "工作项", "project": "项目", "user": "成员",
    "acceptance_photo": "验收图片", "work_item_attachment": "工作项资料", "experience": "经验条目",
    "invitation": "邀请", "import_batch": "导入批次", "process_rule": "工序规则", "template": "公司模板",
    "baseline_event": "知会", "floor": "楼层", "room": "房间",
}

FIELDS = {
    "actualFinish": "实际完成日期", "actualHandover": "实际交房日期", "added": "新增", "affected": "受影响工作项",
    "agent": "代理人", "amount": "金额", "attendance": "出勤", "baselineStatus": "基线状态", "basisCheckId": "放行依据核对",
    "body": "内容", "builtBeforeSign": "后补变更", "cause": "原因", "changeNote": "改动说明", "changeOrder": "变更单",
    "checkId": "核对记录", "closedOn": "闭环日期", "conclusion": "结论", "content": "内容", "copyFrom": "复制自",
    "cost": "费用", "costBearer": "承担方", "count": "数量", "countermeasure": "对策", "coverEventId": "覆盖事件",
    "covered": "已覆盖", "currentSigned": "当前签认版", "discoveryPhase": "发现时点", "drawingVersionId": "图纸版本",
    "dueOn": "约定完成日期", "end": "结束日期", "errorRows": "错误行数", "errors": "错误", "files": "附件",
    "floorId": "楼层", "floors": "楼层", "folder": "分类", "headcount": "人数", "idempotencyKey": "幂等键",
    "isConcealed": "是否隐蔽", "isDraft": "编辑稿", "isProxy": "代理放行", "issue": "问题", "issues": "问题",
    "level": "等级", "mode": "方式", "name": "名称", "notices": "留言", "ownerName": "负责人", "pageNo": "页码",
    "phaseId": "工段", "phaseLogs": "计划留档", "phases": "工段", "photos": "照片", "planLogs": "计划留档",
    "plannedEnd": "计划结束", "plannedFinish": "计划完成日期", "plannedOn": "计划日期", "plannedStart": "计划开始",
    "priceDelta": "费用增减", "progress": "完成度", "qcUserId": "质检人", "reason": "理由", "releaseId": "放行记录",
    "releaseTimeoutHours": "放行时限（小时）", "removed": "移除", "resignWorkItems": "待重签工作项", "revNo": "修订号",
    "revisions": "修订", "roles": "角色", "roomId": "房间", "rooms": "房间", "rules": "规则", "same": "未变化",
    "scheduleDeltaDays": "工期增减（天）", "scopeNote": "施工范围", "sha256": "文件摘要", "size": "大小",
    "source": "来源", "start": "开始日期", "status": "状态", "supplements": "补充事项", "supplementsAdded": "新增补充事项",
    "teamLead": "班组", "template": "模板", "title": "标题", "updated": "更新", "verNo": "版本", "versionNo": "版本",
    "wasCovered": "核对时已覆盖", "wasUnreleased": "覆盖时未放行", "weight": "权重", "workItemId": "工作项",
    "workItems": "工作项", "written": "写入", "x": "横坐标", "y": "纵坐标",
    "roomName": "房间", "floorName": "楼层", "phaseName": "工段", "qcUserName": "质检人", "checkpoints": "检查点",
    "code": "编号", "point": "检查要点", "description": "工作说明", "drawingSetName": "图纸分册",
    "drawingVersionNo": "图纸版本号", "drawingFileSha256": "图纸文件摘要", "acceptanceCriteria": "验收标准",
    "workItemName": "工作项", "snapshot": "快照", "content": "内容", "revisionId": "修订", "signer": "签认人",
}
HIDDEN = {"id", "idempotencyKey", "drawingSetId"}
MAX_LEN = 60


def action(code):
    return ACTIONS.get(code, code)


def object_type(code):
    return OBJECT_TYPES.get((code or "").lower(), code) if code else ""


def _keys(d):
    """隐藏内部 ID：有同名可读字段（如 roomId 与 roomName）时只显示可读字段。"""
    return [k for k in d if k not in HIDDEN and not (k.endswith("Id") and (k[:-2] + "Name") in d)]


def _value(v):
    if isinstance(v, bool):
        return "是" if v else "否"
    if v is None or v == "":
        return "—"
    if isinstance(v, (list, tuple)):
        if v and all(isinstance(x, dict) for x in v):
            return f"{len(v)} 项"
        return "、".join(_value(x) for x in v) if v else "—"
    if isinstance(v, dict):
        return _clip("；".join(f"{FIELDS.get(k, k)} {_value(v[k])}" for k in _keys(v)))
    text = str(v)
    if len(text) == 64 and all(c in "0123456789abcdef" for c in text):
        return text[:12] + "…"  # SHA-256 只显示前 12 位
    return _clip(text)


def _clip(text):
    return text if len(text) <= MAX_LEN else text[:MAX_LEN] + "…"


def values(d):
    """前后值：键翻成中文、值转为可读文本；非字典原样转文本。"""
    if d is None:
        return None
    if not isinstance(d, dict):
        return _value(d)
    return {FIELDS.get(k, k): _value(d[k]) for k in _keys(d)}
