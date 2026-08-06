"""seed_demo 演示数据表（纯数据，无逻辑）。

与 seed_demo 命令分离：本模块只存放演示数据定义，便于阅读与维护；
命令逻辑见 seed_demo.py。所有数据均为虚构，无真实 PII。
"""

from typing import Final

#: (name, gender, age_note, region, occupation, phone_suffix, status, priority, tags)
CUSTOMERS: Final[list[tuple[str, str, str, str, str, int, str, str, list[str]]]] = [
    (
        "演示-张伟明",
        "男",
        "42岁",
        "上海市浦东新区",
        "企业主",
        1,
        "保单服务中",
        "高",
        ["演示-高价值客户", "演示-家庭保单"],
    ),
    (
        "演示-李秀兰",
        "女",
        "40岁",
        "上海市浦东新区",
        "教师",
        2,
        "保单服务中",
        "中",
        ["演示-家庭保单"],
    ),
    ("演示-王建国", "男", "55岁", "北京市朝阳区", "退休", 3, "已见面", "中", ["演示-长期客户"]),
    ("演示-陈慧敏", "女", "35岁", "广州市天河区", "医生", 4, "理赔处理中", "高", ["演示-理赔跟进"]),
    ("演示-刘志强", "男", "30岁", "深圳市南山区", "程序员", 5, "等待回复", "中", ["演示-新客"]),
    ("演示-赵雅芝", "女", "48岁", "杭州市西湖区", "个体户", 6, "明确拒绝", "低", []),
    ("演示-孙立国", "男", "60岁", "南京市鼓楼区", "退休", 7, "多次失约", "中", ["演示-提醒跟进"]),
    ("演示-周玉梅", "女", "52岁", "成都市锦江区", "会计", 8, "长期维护", "低", ["演示-长期客户"]),
    ("演示-吴晓峰", "男", "28岁", "武汉市江汉区", "设计师", 9, "已预约", "中", ["演示-新客"]),
    ("演示-郑丽华", "女", "38岁", "西安市雁塔区", "护士", 10, "已加微信", "中", []),
    ("演示-钱永强", "男", "45岁", "重庆市渝中区", "律师", 11, "待首次联系", "低", []),
    ("演示-冯秀英", "女", "58岁", "天津市和平区", "退休", 12, "已联系", "中", ["演示-长期客户"]),
]

#: (from_idx, to_idx, relation_type)
RELATIONS: Final[list[tuple[int, int, str]]] = [
    (0, 1, "spouse"),
    (2, 0, "referrer"),
    (0, 3, "same_household"),
    (6, 7, "spouse"),
    (4, 8, "referrer"),
    (9, 11, "family"),
    (5, 10, "referrer"),
]

#: 每客户工作事件：(event_type, title, days_ago, summary, next_followup_days)
EVENT_SPECS: Final[dict[int, list[tuple[str, str, int, str, int | None]]]] = {
    0: [
        ("first_meeting", "首次见面沟通", 45, "了解家庭保险现状与预算", 30),
        ("phone_call", "电话回访", 20, "确认保单服务需求", None),
        ("policy_organize", "保单整理", 8, "整理家庭现有保单", None),
    ],
    1: [("wechat", "微信发送保单整理", 15, "约定上门时间", 7)],
    2: [
        ("customer_activity", "参加客户答谢会", 30, "现场交流", None),
        ("policy_organize", "保单整理", 10, "整理现有保单", 30),
    ],
    3: [
        ("claim_process", "提交理赔材料", 5, "材料已提交保险公司", None),
        ("material_collection", "补充材料沟通", 2, "待补充发票原件", 3),
    ],
    4: [("first_meeting", "初步接触", 60, "暂无明确意向", None)],
    5: [("phone_call", "电话沟通", 50, "明确拒绝，暂不联系", None)],
    6: [
        ("home_visit", "上门服务", 25, "客户临时有事未见面", 15),
        ("phone_call", "电话沟通", 12, "再次约访未果", 7),
    ],
    7: [("wechat", "微信问候", 18, "保持联系", None)],
    8: [("first_meeting", "首次见面", 6, "约定下次详谈方案", 7)],
    9: [("wechat", "微信加好友", 4, "初步了解需求", None)],
    10: [],
    11: [("phone_call", "电话首次联系", 9, "客户有意向了解养老险", 14)],
}

#: 每客户沟通记录：(channel, days_ago, quick_result, content, next_followup_days)
COMM_SPECS: Final[dict[int, list[tuple[str, int, str, str, int | None]]]] = {
    0: [
        ("phone", 20, "wants_meeting", "约好下周上门", 7),
        ("wechat", 8, "", "发送保单整理资料", None),
    ],
    1: [("meeting", 14, "wants_meeting", "确认家庭保单方案", 7)],
    2: [("company_activity", 30, "call_later", "答谢会现场交流", None)],
    3: [
        ("phone", 5, "call_later", "保险公司要求补发票", 3),
        ("wechat", 2, "", "客户已准备补材料", None),
    ],
    4: [("wechat", 60, "time_uncertain", "客户表示再考虑", 30)],
    5: [("phone", 50, "not_needed", "客户明确不需要", None)],
    6: [
        ("phone", 25, "missed", "未接", 15),
        ("phone", 12, "hung_up", "接通后挂断", 7),
    ],
    7: [("sms", 18, "", "节日问候", None)],
    8: [("phone", 6, "wants_meeting", "约见详谈方案", 7)],
    9: [("wechat", 4, "wants_wechat", "微信沟通需求", None)],
    10: [],
    11: [("phone", 9, "call_later", "了解养老险，稍后再联", 14)],
}

#: (customer_idx, task_type, title, due_offset_days, priority)
TASKS: Final[list[tuple[int, str, str, int, str]]] = [
    (0, "call", "跟进张伟明保单回访", -1, "高"),
    (1, "wechat", "联系李秀兰确认保单整理", 0, "中"),
    (3, "claim_material", "提醒陈慧敏补充理赔发票", 3, "高"),
    (4, "meeting", "约见刘志强介绍方案", 7, "中"),
    (2, "deliver_materials", "给王建国送保单合同", 5, "低"),
    (6, "policy_organize", "孙立国保单整理", 10, "中"),
]

#: (name, category)
ALBUMS: Final[list[tuple[str, str]]] = [
    ("演示-证件资料", "id_docs"),
    ("演示-保单资料", "policy_docs"),
]

#: (filename, customer_idx, album_idx, sensitivity, important)
DOCUMENTS: Final[list[tuple[str, int, int | None, str, bool]]] = [
    ("演示-张伟明-身份证.png", 0, 0, "highly_sensitive", False),
    ("演示-张伟明-银行卡.png", 0, 0, "highly_sensitive", False),
    ("演示-张伟明-保单合同.png", 0, 1, "sensitive", True),
    ("演示-李秀兰-身份证.png", 1, 0, "highly_sensitive", False),
    ("演示-陈慧敏-诊断证明.png", 3, 1, "sensitive", True),
    ("演示-陈慧敏-医疗发票.png", 3, 1, "sensitive", False),
    ("演示-王建国-投保单.png", 2, 1, "normal", False),
    ("演示-孙立国-理赔申请书.png", 6, 1, "normal", False),
    ("演示-刘志强-沟通截图.png", 4, None, "normal", False),
    ("演示-活动照片.png", 0, None, "normal", False),
]

#: (policyholder_idx, insured_idx, insurer, name, policy_no,
#:  insurance_type, premium, frequency, status)
POLICIES: Final[list[tuple[int, int, str, str, str, str, str, str, str]]] = [
    (0, 0, "平安人寿", "平安福终身寿险", "DEMO-0001", "终身寿险", "5200", "annual", "active"),
    (1, 1, "中国人寿", "康宁终身重疾险", "DEMO-0002", "重疾险", "6800", "annual", "paying"),
    (0, 0, "泰康人寿", "泰康尊享医疗险", "DEMO-0003", "医疗险", "1200", "monthly", "paid_up"),
    (2, 2, "太平洋保险", "金佑人生养老险", "DEMO-0004", "养老年金", "8000", "annual", "lapsed"),
    (3, 3, "新华保险", "健康福星医疗险", "DEMO-0005", "医疗险", "3600", "annual", "active"),
]

#: (customer_idx, policy_idx, claim_type, name, status)
CLAIMS: Final[list[tuple[int, int, str, str, str]]] = [
    (3, 4, "medical", "演示-陈慧敏医疗险理赔", "collecting_materials"),
    (0, 0, "accident", "演示-张伟明意外险理赔", "closed"),
    (6, 2, "critical_illness", "演示-孙立国重疾险咨询", "waiting_materials"),
]
