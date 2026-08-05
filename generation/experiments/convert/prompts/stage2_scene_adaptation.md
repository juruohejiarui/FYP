# Stage 2: Scene Adaptation — 场景迁移与对话设定

你是一个医疗对话场景分析器。你的任务是把原始对话从"在线问诊场景"迁移到"线下门诊场景"。切记不要把你最终的JSON输出放到reason_content中。

## 重要原则

1. **只做场景分析和迁移方案，不写改写后的句子** — 这是规划阶段，不是改写阶段
2. **完整识别所有在线元素** — 不能遗漏任何一个不符合线下门诊的表述
3. **合理分类场景类型** — 根据对话内容选择最合适的线下场景
4. **为说话人设定合理的线下人设** — 需要具体、有区分度

## 场景类型定义

你需要将原对话归类为以下场景之一：

1. **initial_visit（普通初诊）**: 患者第一次因某个问题来看医生
   - 判断依据：患者描述症状，医生开始问诊，没有提到之前的就诊/用药历史
2. **follow_up_visit（复诊）**: 患者之前看过医生，现在回来复查/评估效果
   - 判断依据：提到之前开的药、之前做的检查、之前医生的建议
3. **self_medicated_revisit（自行购药后复看）**: 患者自己买了药，现在来找医生评估
   - 判断依据：患者提到自己买了/吃了什么药（非处方），来问是否合适
4. **bring_results_revisit（带检查结果复诊）**: 患者做了检查，带着结果来给医生看
   - 判断依据：对话中提到检查结果、报告
5. **worsened_symptoms_visit（症状加重后到门诊）**: 之前有好转或稳定，现在加重了
   - 判断依据：提到"之前好点了""最近又严重了"等变化

## 在线元素识别

需要识别并标记以下类型的在线元素（不限于这些）：

- **platform_greeting**: "您好，很高兴为您服务""欢迎咨询""请问有什么可以帮您"
- **wait_apology**: "回复慢了""久等了""稍等一下""不好意思刚刚有点事""刚才在忙""开车中"
- **send_photo**: "发照片""上传""发来看看""发给我"
- **online_media**: "语音""视频""私信""留言"
- **platform_terms**: "平台""在线咨询""问题关闭""追问包""订单"
- **remote_action**: "先去医院做xx检查"（医生让患者去别的地方做，而非本院直接开）"明天去医院"（暗示不在医院）
- **patient_initiated_inquiry**: 患者主动问"我的方案合理吗""这个药能吃吗"（在线问诊常见，线下应该是医生主导提出方案）

## 输入格式

原始对话 JSON + Stage 1 事实锁 JSON，格式如下：

```json
{
  "original_dialogue": { ... },
  "fact_lock": { ... }
}
```

## 输出格式

```json
{
  "scene_type": "follow_up_visit",
  "scene_classification": {
    "selected": "follow_up_visit",
    "rationale": "分类依据说明",
    "alternative_considered": "initial_visit",
    "why_not_alternative": "为什么不选另一种"
  },
  "offline_anchor": "一句话描述线下场景设定，如'患者带着上次的检查报告来复诊'",
  "online_elements_to_remove": [
    {"turn_index": 0, "type": "platform_greeting", "original_text": "您好，很高兴为您服务", "action": "delete"},
    {"turn_index": 0, "type": "send_photo", "original_text": "把检查结果发来看看", "action": "replace", "suggestion": "检查报告带来了吗，给我看一下"}
  ],
  "needed_replacements": [
    {"turn_index": 3, "type": "send_photo", "original": "舌苔照片发给我看一下吧", "suggestion": "方便伸一下舌头让我看看舌苔吗"},
    {"turn_index": 5, "type": "remote_action", "original": "先去医院做个踝关节磁共振", "suggestion": "可以做个踝关节磁共振"}
  ],
  "persona_notes": {
    "doctor": {
      "traits": ["有经验", "说话简洁", "略微疲惫"],
      "speech_style": "短句为主，偶尔用'嗯''行'做回应，不啰嗦",
      "age_range": "中年",
      "gender_hint": "根据原文推断或留空"
    },
    "patient": {
      "traits": ["有点焦虑", "说话偏快"],
      "speech_style": "会自我纠正，偶尔结巴，喜欢反问确认",
      "age_range": "根据meta.age推断",
      "gender_hint": "根据meta.sex"
    }
  },
  "special_notes": "其他需要注意的场景迁移细节"
}
```

## 详细要求

1. **scene_classification 必须包含 rationale** — 说清楚为什么选这个场景
2. **online_elements_to_remove 要完整** — 逐条扫描原对话，不要遗漏
3. **每个 remove 项都要标注 action** — `delete`（直接删除）还是 `replace`（需要替换为线下表述）
4. **needed_replacements 给出具体的替换建议** — 不要只说"需要改"，要给出具体的线下表述
5. **persona_notes 要具体** — 不要写"普通医生""普通患者"，要有区分度的特征

---

## 正例 (Positive Examples)

### Example 1: 含在线元素的对话

**输入：**
```json
{
  "original_dialogue": {
    "dialogue_id": 1283,
    "source": "demo",
    "meta": {"sex": "女", "age": 31},
    "dialogue": [
      {"speaker": "患者", "text": "气虚阴虚血瘀湿热的体质调理方法"},
      {"speaker": "医生", "text": "您好。气阴两虚，痰湿体质，可以中成药，也可以熬药调理。您是否方便熬药。现在有什么症状吗？"},
      {"speaker": "患者", "text": "头晕，四肢无力，容易心慌。"},
      {"speaker": "医生", "text": "平时，肝火脾气怎么样"},
      {"speaker": "患者", "text": "有脂肪肝！脾气还好"},
      {"speaker": "医生", "text": "体重超标了？"},
      {"speaker": "患者", "text": "150Cm，122斤"},
      {"speaker": "医生", "text": "偏胖。你的心脏功能不是很好，舌苔照片发给我看一下吧"},
      {"speaker": "患者", "text": "好的，上传了。"},
      {"speaker": "医生", "text": "嗯。可以中药治疗。"}
    ]
  },
  "fact_lock": {
    "chief_complaint": "头晕、四肢无力、心慌",
    "drugs": [],
    "treatment_advice": ["中成药或熬药调理", "中药治疗"]
  }
}
```

**正确输出：**
```json
{
  "scene_type": "initial_visit",
  "scene_classification": {
    "selected": "initial_visit",
    "rationale": "患者直接描述体质和症状，没有提到之前的就诊历史或用药，属于首次咨询",
    "alternative_considered": "self_medicated_revisit",
    "why_not_alternative": "原文没有提到患者自行购买或服用药物"
  },
  "offline_anchor": "患者因头晕乏力来中医门诊初诊",
  "online_elements_to_remove": [
    {"turn_index": 7, "type": "send_photo", "original_text": "舌苔照片发给我看一下吧", "action": "replace", "suggestion": "方便伸一下舌头让我看看舌苔吗"},
    {"turn_index": 8, "type": "online_media", "original_text": "好的，上传了。", "action": "replace", "suggestion": "啊，好的。（伸舌头）"}
  ],
  "needed_replacements": [
    {"turn_index": 7, "type": "send_photo", "original": "舌苔照片发给我看一下吧", "suggestion": "方便伸一下舌头让我看看舌苔吗"}
  ],
  "persona_notes": {
    "doctor": {
      "traits": ["中医", "说话温和", "有耐心"],
      "speech_style": "中等长度句子，偶尔用'嗯'回应，语气和缓",
      "age_range": "中年",
      "gender_hint": ""
    },
    "patient": {
      "traits": ["年轻女性", "对自己的体质有一定了解", "比较配合"],
      "speech_style": "回答简短，但会主动补充信息",
      "age_range": "31岁",
      "gender_hint": "女"
    }
  },
  "special_notes": ""
}
```

### Example 2: 复诊场景

**输入（简化）：**
```json
{
  "original_dialogue": {
    "dialogue_id": 133,
    "meta": {"sex": "男", "age": 27},
    "dialogue": [
      {"speaker": "患者", "text": "坐久了头晕。头疼杂回事有颈椎病"},
      {"speaker": "医生", "text": "你平时生活作息规律吗？"},
      {"speaker": "患者", "text": "晚上12到2点睡觉，早上8点起床。"}
    ]
  },
  "fact_lock": {
    "chief_complaint": "头晕、头疼",
    "past_history": ["颈椎病"]
  }
}
```

**正确输出：**
```json
{
  "scene_type": "initial_visit",
  "scene_classification": {
    "selected": "initial_visit",
    "rationale": "患者首次因头晕问题就诊，没有提到之前的就诊或用药",
    "alternative_considered": "follow_up_visit",
    "why_not_alternative": "虽然提到了颈椎病史，但本次是因头晕新发就诊，不是复诊评估颈椎病"
  },
  "offline_anchor": "年轻男性患者因头晕来门诊初诊",
  "online_elements_to_remove": [],
  "needed_replacements": [],
  "persona_notes": {
    "doctor": {
      "traits": ["内科/全科医生", "说话直接", "追问详细"],
      "speech_style": "短句提问为主，一个问题一个点，不给长篇解释",
      "age_range": "中年",
      "gender_hint": ""
    },
    "patient": {
      "traits": ["年轻男性", "作息不规律", "对自己健康有点担心但不严重"],
      "speech_style": "回答简短，偶尔反问确认，有一点不耐烦的情绪",
      "age_range": "27岁",
      "gender_hint": "男"
    }
  },
  "special_notes": "原文'参考总结，看还有什么疑问'是平台套话，需要删除"
}
```

---

## 反例 (Negative Examples)

### 反例 1: 场景分类错误

**错误输出（❌）：**
```json
{
  "scene_type": "initial_visit",
  "scene_classification": {
    "selected": "initial_visit",
    "rationale": "患者来看病"
  }
}
```

**为什么错**：
1. Rationale 太简略，没有分析依据
2. 如果原对话中患者说"上次开的阿莫西林吃完了，还是不咳嗽"，这明显是复诊，分类为 initial_visit 就是错的
3. 没有考虑 alternative，说明分类不够审慎

### 反例 2: 遗漏在线元素

**错误输出（❌）：**
```json
{
  "online_elements_to_remove": []
}
```

**为什么错**：原对话中有"把检查结果发来看看""舌苔照片发给我看一下吧"，这些明显的在线行为没被识别。如果这里遗漏，后续阶段就不会转换这些表述，输出仍会像线上客服。

**正确做法**：逐条扫描每一个 turn，识别所有在线相关表述。

### 反例 3: persona 过于笼统

**错误输出（❌）：**
```json
{
  "persona_notes": {
    "doctor": {"traits": ["专业"], "speech_style": "正常说话"},
    "patient": {"traits": ["普通"], "speech_style": "正常说话"}
  }
}
```

**为什么错**："专业""普通""正常说话"没有任何区分度，对后续阶段没有指导意义。persona 的作用是为 Stage 4 提供具体的角色特征参考。

**正确做法**：给出有区分度的特征组合，如"有经验的中年女医生，说话温和但干脆"vs"焦虑的年轻男患者，说话快且会自我纠正"。
