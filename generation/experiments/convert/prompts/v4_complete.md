# B 模式：临床约束 → 线下门诊 → 真实转录

## 总目标与分层

任务不是把线上问答逐句改口语，而是以原内容中**可靠的临床知识和病例约束**为素材，重新导演一次可信的医院门诊部真实发生的线下门诊，再把它写成未经剧本打磨的录音转写。

工作链路固定为：

> 原始线上文本 → Clinical Brief（临床约束）→ Encounter Director（门诊导演）→ Spoken Performance Plan（口语表演计划）→ 新的线下面诊转录

这是严格的 **B 模式**：保留主问题、症状与病程、已有诊断/检查/药物、医生解释、治疗、缓解、预防、生活方式、忌口、随访和关键否定/条件；不保留原话、原轮次、原句法或原有问答顺序。

### 绝不允许的事

- B 模式**不新增患者病例细节**：不能补症状、病程、诱因、检查结果、既往史、用药史、过敏史、孕育状态或疗效。也不能为了让医生能问诊而让患者凭空回答。
- 不新增、不替换、不夸大医学结论、诊断、检查、药物、剂量、治疗、风险、注意事项或安慰性判断。
- 不把“没有、偶尔、考虑、可以、不一定、问是否”说成相反、更重、更频繁、确诊或必须。
- 不把线上特有内容原样搬到线下：上传、发图、语音/视频、平台、在线、刚看到、在开车准备去医院、到正规医院检查等。若“开车时头晕”是症状发生背景，则保留其病史意义。
- 最终生成阶段不得尝试复述未提供的原对话；它只以输入的三个抽象对象为准。

### 创作自由与口语标准

在不碰临床约束的前提下，可自由决定开场、谁先说、信息呈现顺序、追问形式、收尾、轮数、口头习惯和对话张力。这里的“真实”不是更通顺，而是更像转写：短、互相接得上、有局部卡顿，但不是整段故意演结巴。

患者和医生都可能出现：重复/结巴、嘴瓢、未修正但可理解的口误、倒装（“有用吗这个？”）、省略、语气词、无意义填充（“这个……”）、局部语法不完整、自我修正、术语检索和 echo。一次发言可有零个或多个现象；它们由人设、信息压力和这一次对话的偶然性驱动，**不按每人、每轮、每段配额分派**。医生的专业性体现为最终传达的医学含义可靠，不体现为永远流畅。

但“可用”不等于可被忽略：五个及以上实质轮的对话，必须让本次抽取的人设和口语现象可被读者听见。至少实现三处非纯语气词的口语结构，并至少有一处来自倒装、词块重复、起句重启、术语检索、省略或词序不完整；这些可以集中在一人或一段较有压力的表达里。少于五个实质轮则允许只有零到一处。禁止固定地让每个人各结巴一次。

可自然使用日常说法：肚子、上厕所、尿尿、拉屎、看病、吃药、没啥用、不见好、堵得慌、咋回事、这毛病、反反复复、拖着、得、要不、行、没事儿、挺难受的。患者不必文雅，医生也不必像健康宣教稿；但口语化不得改变医学语义。

## 共同 JSON 契约

- 每个 stage 只输出**一个** JSON object，不要 Markdown、解释、前后缀或数组顶层。
- 下列格式中的每个字段都是必填。数组可为 `[]`；不确定值使用 JSON `null`，不能省略字段，不能填“未知”。
- 文中出现的 `A | B` 仅表示枚举选择；它不是 JSON 中可照抄的字符串。所有格式示例均用 `null` 或普通占位值展示类型，字段允许值另在示例后明确列出。
- Stage 0 的结果只用于补全 meta；Stage 1–3 仅供后续使用；Stage 4 的 object 是最终 JSONL 行；Stage 5 不写入最终文件。
- 最终 `text` 不用阿拉伯数字、英文字符、括号动作说明或线上平台词。数字改为自然中文说法。相邻两轮必须换说话人。

## 人设来源库：必须从这里自由选择，而不是压成“患者/医生都很自然”

- `chronic_self_manager`：患者长期和同一类问题打交道，有一点自我管理语言；可以更快抓住“减量、复发、忌口、检查”这类 Brief 已经出现的词，但仍可能把句子说断、问得很生活化。
- `medical_worker_or_student`：患者懂得一些术语，记忆不清晰，可能用诊断名/检查名反问，或先说半句术语又换成日常词。**不能**因此补出原 Brief 没有的诊断、检查、疗法或同事意见。
- `researched_layperson`：患者会说“我看了下”“这个是不是……”一类半懂不懂的提问，但只能围绕已知临床约束，可能引进新的网传方案，但是**一定**会被医生用网传方案不可信等原因否定。
- `little_medical_knowledge`：患者更多用“这毛病、堵得慌、咋回事”一类日常表达，医生需要把已有结论拆短解释；不是把患者写成低智，也不是强行结巴。
- `very_familiar`：医生用语利落，但也可以有简短 echo、俚语、倒装和轻微嘴飘。
- `ordinary_outpatient_style`：医生是常见门诊表达，边问边接话，常把患者关键词复述一半。
- `less_familiar_with_topic`：医生可能先检索或用更泛的说法，术语/药名可重启；最终只能落回 Brief 已有结论，不能因“不熟”虚构模糊诊断。
- `early_career`：医生解释会略显按步骤、偶尔重复连接词，但不必写成书面教学。
- `tired_but_careful`：医生有“嗯、这个、是吧”、短暂停顿、词序滑动或口误；医学含义仍完整，不能表现为粗暴、漏诊或乱开药。
- `other: 一个自定义的更好的人设描述句子`：你允许有一些别的想法，我们鼓励使用你自创的符合实际的人设，只需要接下来 stage 的操作者能理解即可，描述方式参照上面提供的预设人设。

这些人设来源可影响同一临床素材的表面路径。例如同样是“可以查过敏原、未查过、不是永久忌口”：慢病自我管理者可以先问“那我是不是得一直躲着吃”；医学生式患者可能先问“过敏原那个没做过，能补吗”；疲惫但谨慎的医生可说“没查过是吧？过敏……过敏原能查的”。三种都不能增加过敏原种类、皮疹频率或治疗方案。

无论是何种人设组合，始终有如下规则：
 - 患者极少怀疑或不相信医生的指导和解释。
 - 患者主动提出某种治疗方案/药物方案。

<!-- STAGE: stage0_meta_inference -->
# Stage 0：Meta Inference

仅补全输入 `meta` 中缺失的 `sex`、`age`、`language`。不改写对话，不推断情绪、人设或口语习惯。已有值不改。只有直接证据才推断；证据不足就为 `null`。

## 输入

```json
{"dialogue_id":0,"source":"","meta":{"sex":null,"age":null,"language":null},"dialogue":[{"speaker":"患者","text":"..."}]}
```

## 输出

```json
{"sex":null,"age":null,"language":null,"evidence":{"sex":"string","age":"string","language":"string"},"confidence":"low"}
```

`sex` 只能是 `男`、`女` 或 `null`；`age` 只能是非负整数或 `null`；`language` 只能是 `Chinese` 或 `null`；`confidence` 只能是 `high`、`medium` 或 `low`。

## 正例

输入首句含“（女，二十一岁）慢性荨麻疹能查过敏原吗？”，三项均为空：

```json
{"sex":"女","age":21,"language":"Chinese","evidence":{"sex":"首句明示女","age":"首句明示二十一岁","language":"对话为中文"},"confidence":"high"}
```

<!-- STAGE: stage1_clinical_brief -->
# Stage 1：Clinical Brief

从原始线上内容中抽取**所有需要保留的临床约束**，为重新创作服务。不是逐轮账本，不复述原句，也不设计台词。

## 抽取规则

每条临床信息都要成为一个独立 constraint，覆盖以下所有相关类别：`reason_for_visit`、`symptom`、`course`、`condition`、`test`、`test_result_or_status`、`medication`、`treatment`、`self_care`、`prevention`、`relief`、`avoidance`、`follow_up`、`doctor_explanation`、`patient_concern`、`negation`、`uncertainty_or_condition`、`other_clinical`。

- 医生给出的生活方式、预防、缓解、忌口、复查、观察等内容和药物一样是需要保留的临床事实，不能因不是“诊断/症状”而漏掉。
- 保留说话人立场、限定词和方向。例如“偶尔痛”“没查过”“能不能查”“不一定要永远忌口”都不能压扁。
- 同义重复可合并；一条原始长句内的多个独立临床点必须拆开。
- `must_surface` 表示最终对话必须以自然方式表达；`may_merge` 表示可与同类约束合并在一个短轮中但不能遗漏。
- `offline_transform_notes` 只记录如何去除线上痕迹，不得创造当面检查或新病史。

## 输入

输入为完整原始记录 JSON。

## 输出

```json
{
  "case_anchor":{"reason_for_visit":"string","minimum_context":["string"]},
  "clinical_constraints":[
    {"id":"C1","category":"symptom","origin":"patient","content":"最小医学语义","polarity":"affirmed","surface_requirement":"must_surface","evidence_turns":[0]}
  ],
  "medical_boundaries":{"must_not_add":["string"],"must_not_strengthen":["string"],"must_not_reverse":["string"]},
  "offline_transform_notes":[{"source_type":"remote_action | remote_state | remote_exam_request | symptom_context | none","instruction":"string"}],
  "creative_permissions":{"may_reorder":true,"may_replace_all_source_wording":true,"may_add_nonclinical_interaction":true,"may_add_synthetic_case_detail":false}
}
```

`category` 只能是规则中列出的类别之一；`origin` 只能是 `patient`、`doctor`、`both`；`polarity` 只能是 `affirmed`、`denied`、`question`、`conditional`、`uncertain`；`surface_requirement` 只能是 `must_surface` 或 `may_merge`。

## 正例一：把“忌口”抽成临床约束，而不是保留原问句

原料含：慢性荨麻疹；未查过过敏原；患者问能否查、查到后是否永远忌口；医生说可以查、无需永远忌口、体质会变化。

```json
{
  "case_anchor":{"reason_for_visit":"慢性荨麻疹患者担心饮食限制","minimum_context":["已有慢性荨麻疹","未做过过敏原检查"]},
  "clinical_constraints":[
    {"id":"C1","category":"condition","origin":"patient","content":"慢性荨麻疹","polarity":"affirmed","surface_requirement":"must_surface","evidence_turns":[0]},
    {"id":"C2","category":"test_result_or_status","origin":"patient","content":"此前未查过过敏原","polarity":"denied","surface_requirement":"must_surface","evidence_turns":[1]},
    {"id":"C3","category":"test","origin":"doctor","content":"可以检查过敏原","polarity":"affirmed","surface_requirement":"must_surface","evidence_turns":[3]},
    {"id":"C4","category":"patient_concern","origin":"patient","content":"担心查到过敏原后需要长期或永久忌口","polarity":"question","surface_requirement":"must_surface","evidence_turns":[0,2]},
    {"id":"C5","category":"doctor_explanation","origin":"doctor","content":"不需要永远忌口，体质会变化","polarity":"affirmed","surface_requirement":"must_surface","evidence_turns":[4]}
  ],
  "medical_boundaries":{"must_not_add":["具体过敏原","忌口清单","检查项目细节"],"must_not_strengthen":["不得把可以检查说成必须检查"],"must_not_reverse":["不得把不需要永远忌口改为必须长期忌口"]},
  "offline_transform_notes":[{"source_type":"none","instruction":"无线上动作需要处理"}],
  "creative_permissions":{"may_reorder":true,"may_replace_all_source_wording":true,"may_add_nonclinical_interaction":true,"may_add_synthetic_case_detail":false}
}
```

## 正例二：生活方式/缓解也必须锁住

若内容含“慢性前列腺炎、尿不尽、偶尔尿痛但不经常、最近没吃药；规律生活、少辛辣、不抽烟喝酒、不久坐熬夜、多运动、放松、温水坐浴；可吃沙巴棕胶囊”，必须分别抽出所有症状限定、药物状态、每一项生活建议、温水坐浴和药物。不能只留下“慢性前列腺炎、沙巴棕胶囊”。

<!-- STAGE: stage2_encounter_director -->
# Stage 2：Encounter Director

仅根据 Clinical Brief 导演一场新的线下面诊。不要写最终台词，不要找回或模拟原始措辞。允许大量创意，但不能新增任何临床信息或患者病例细节。

## 规则

- 选择现实的门诊框架（初诊/复诊/用药咨询/检查咨询/结果解读/不明），设计新的对话弧线；不需要复刻线上问答次序。
- 分别捏两个临场人设。人设只能描述互动方式、说话节奏、知识表达方式和口头习惯，不能新增情绪事实、职业事实、疾病事实或诊疗结论。人设标签可以有多个，允许进行组合，通过 `|` 进行标签分割。
- 两人的差别主要是医学解释权，**不是**“医生永远顺、患者必结巴”。医生可嘴飘、术语重启、echo；患者可熟悉术语或完全生活化。
- 人设可以也应该有**非病例的来源**，这不是新增病例细节：患者可设为长期慢病的自我管理者、医学相关从业者、医学生、网上做过功课但半懂不懂的人，或几乎没有医疗知识的人；医生可设为对这类病很熟、普通门诊经验型、对该问题不那么熟、刚工作不久，或当班有些疲惫。它们可以影响术语熟练度、追问方式、语速、口癖、嘴飘和解释方式。
- 上述来源可以只作为“幕后人设”，不必让角色直接说“我是医学生/我刚上班”。如果写进台词，必须是自然、非临床的身份信息，且不得借此新增病例事实。无论人设如何，最终医学含义仍必须严格符合 Clinical Brief；“不熟/疲惫”只能改变表达，不允许改错医学结论。
- `personas` 不是可有可无的文案：每个角色必须给出二到四个 `signature_habits`，且两人至少有两个不同的习惯。习惯应具体到生成可执行的形态，例如“担心时把关键词放句尾问：`要忌很久吗这个？`”“接话先 echo 半句”“药名说到一半会重启”“常用`这个、哈、是吧`做承接”“回忆时会重复动词”。不要只写“自然、焦虑、耐心、口语化”。
- `disfluency_profile` 要说明什么场景下会出现、哪些现象不适合滥用。例如患者可在主诉/担忧时词块重复，医生可在解释前 echo 或术语检索；二人都可有口误，但不能借口误改变临床含义。
- 允许的桥接只是不携带临床新信息的开场、承接、复述、感谢、请坐等。若设计追问，它只能引出 Clinical Brief 中已有且将在后续表述的 constraint。

## 输入

```json
{"meta":{...},"clinical_brief":{...}}
```

## 输出

```json
{
  "visit_frame":"initial_consultation",
  "offline_premise":"string",
  "encounter_arc":["string"],
  "personas":{
    "patient":{"persona_source":"chronic_self_manager | medical_worker_or_student | researched_layperson | little_medical_knowledge | mixed","interaction_style":"string","medical_literacy":"low","signature_habits":["string"],"lexical_palette":["string"],"disfluency_profile":{"likely_contexts":["string"],"preferred_forms":["string"],"avoid":["string"]}},
    "doctor":{"persona_source":"very_familiar | ordinary_outpatient_style | less_familiar_with_topic | early_career | tired_but_careful","interaction_style":"string","medical_literacy":"professional","signature_habits":["string"],"lexical_palette":["string"],"disfluency_profile":{"likely_contexts":["string"],"preferred_forms":["string"],"avoid":["string"]}}
  },
  "safe_bridges":[{"purpose":"string","may_appear":true,"adds_clinical_information":false}],
  "constraint_presentation_notes":[{"constraint_id":"C1","presentation_goal":"string"}],
  "forbidden_additions":["string"]
}
```

`visit_frame` 只能是 `initial_consultation`、`follow_up`、`medication_consultation`、`test_consultation`、`results_discussion`、`unclear`；患者 `medical_literacy` 只能是 `low`、`mixed`、`familiar`，医生固定为 `professional`。`patient.persona_source` 与 `doctor.persona_source` 分别只能从格式中给出的五项中选择。每名角色的 `signature_habits` 必须有二至四项，`lexical_palette` 必须有二至五项。

## 正例：同一荨麻疹 Brief 的一种全新导演

```json
{
  "visit_frame":"test_consultation",
  "offline_premise":"患者因慢性荨麻疹及对饮食限制的顾虑来咨询",
  "encounter_arc":["患者先绕着饮食限制开口","医生用已有检查状态把话题落到过敏原","患者确认最怕的是一辈子不能吃","医生解释已有结论","患者用日常短句收尾"],
  "personas":{"patient":{"persona_source":"chronic_self_manager","interaction_style":"反复自己琢磨过饮食，开头有点兜圈，关键担忧会把关键词重复确认","medical_literacy":"mixed","signature_habits":["主诉开头偶尔重复词块，如‘我这、我这个’","担心时把问题倒装到句尾，如‘要忌很久吗这个’","听懂后用‘哦这样啊’而非固定说好"],"lexical_palette":["这个","得","咋","哦这样啊"],"disfluency_profile":{"likely_contexts":["刚说主诉","追问长期限制"],"preferred_forms":["起句重启","词块重复","倒装"],"avoid":["每轮都加省略号"]}},"doctor":{"persona_source":"tired_but_careful","interaction_style":"接话快，偶尔先 echo 患者关键词再解释；表达会卡一下但最终术语准确","medical_literacy":"professional","signature_habits":["用半句 echo 接话，如‘忌口这块啊’","术语前偶尔轻重启，如‘过敏……过敏原’","解释后常以‘是吧、哈’收短"],"lexical_palette":["嗯","这块","是吧","哈"],"disfluency_profile":{"likely_contexts":["接住患者担心","提到检查名称"],"preferred_forms":["echo","术语重启","短承接"],"avoid":["把完整医学结论说断到无法理解"]}}},
  "safe_bridges":[{"purpose":"门诊开场","may_appear":"true","adds_clinical_information":false},{"purpose":"请患者确认此前是否检查","may_appear":"true","adds_clinical_information":false}],
  "constraint_presentation_notes":[{"constraint_id":"C2","presentation_goal":"用医生确认或患者回忆自然带出"},{"constraint_id":"C5","presentation_goal":"分成一句解释和一句自然收尾"}],
  "forbidden_additions":["具体食物禁忌","新的皮疹频率","新的检查结果"]
}
```

<!-- STAGE: stage3_spoken_performance_plan -->
# Stage 3：Spoken Performance Plan

把导演意图转成可表演的短轮骨架。你规划交流动作、约束覆盖、长句切分和可选口语现象，不写最后台词，也不得从未给出的源文本补内容。

## 规则

- 每个 `clinical_constraint_ids` 必须存在于 Brief。所有 `must_surface` 约束都要在 `coverage` 中出现。
- `persona_source` 必须真实影响计划：慢病自我管理者/医学相关患者可让已有术语或已有治疗方向出现得更早、更简洁；医疗知识较少者可让同一事实先以生活话出现、再由医生用已有术语接住。医生的熟悉度、疲惫度或工作年限只能改变口语节奏和解释形状，不能改变任何临床约束。
- 可完全重排约束；一个医学问题不要隔很多轮才回答，除非中间是引出已有事实的必要确认。
- 每轮通常八至三十个汉字，最多四十个汉字；一次**只**推进一个（偶尔两个）交流动作或**不超过两个**事实点。
  - 一种药物/治疗方式/护理方式/症状/...为一个事实。
  - 一次提问/回答/追问/安抚/警告/...是一个交流动作
- 源内容含多个建议、治疗、药物、解释或问题，亦或是内容较长的时候时主动拆轮。中间可插简单回应、echo 或只引出后续已知答案的询问，可以增加类似Q：“还有什么别的不舒服没有”/“还有什么需要注意的”+A:“别的倒没什么了”/“目前就这些” 这一类终止冗余 turn。但是不能添加不存在于 fact 的会逼出新病例信息的开放问题。
- 注意，症状询问时最好不要医生在患者或者医生自己先前完全没有提过该症状或者相关症状，或者上下文无关时通过猜测/确认的方式询问患者，如：
  - 患者先前提到自己头疼，反例：医生直接提问“昨天是不是疼得更勤？”，这不符合正常人思维；正例1：“那昨天呢？有没有什么变化，一样还是更严重了？” 猜测或者候选；正例2：“昨天有没有更勤了之类的？”不确定地提出自己的猜测；正例3：“昨天有变化吗，是不是好点了？”和正例2类似，但反向猜测。
- 五个及以上实质轮时，必须从 Stage 2 两人的 `signature_habits` 中各挑出一至三个本次要实现的习惯，写进 `persona_realization_targets`。同时在相应 turn 的 `spoken_candidates` 中标记承载它的具体形态。整段至少计划三处非纯语气词的口语结构，其中至少一处为倒装、词块重复、起句重启、术语检索、省略或词序不完整；不可全是“嗯/哦”。这不是“每人固定结巴一次”的配额：可以让某一角色的两个习惯集中出现，另一角色只以一次 echo 或句尾口癖显影，也必须保留干净短句。
- 医学术语、药物、治疗名可以卡壳/重启/嘴飘，前提是当前或紧邻下一轮能明确还原 Brief 的正确医学含义。
- **注意**：相邻 turn 的 `speaker` 不得相同。
- 可以通过回应，赞同等等，增强两人的互动性。
- **注意**上下文问题，比如先前一方完全没有提到某个现状、情况，那么接下来对方就不能认为此人有这样的现状、情况。你需要假设两人先前完全不认识不了解。
  - 但是医生可以阅读病人病历，先前医生可以说明查看病历的请求，然后之后表达从病历阅读到某些信息。
  - 或者其他可以了解病人既往病史、生活习惯和治疗方案等的方法。

## 输入

```json
{"meta":{...},"clinical_brief":{...},"encounter_director":{...}}
```

## 输出

```json
{
  "dialogue_rhythm":"brief_QA",
  "turn_plan":[
    {"id":"T1","speaker":"患者","communicative_action":"string","clinical_constraint_ids":["C1"],"length_target":"short","spoken_candidates":["string"],"must_avoid":["string"]}
  ],
  "persona_realization_targets":{"patient":["string"],"doctor":["string"]},
  "coverage":[{"constraint_id":"C1","turn_ids":["T1"]}],
  "long_turn_splits":[{"constraint_ids":["C1","C2"],"split_strategy":"string","permitted_bridge":"string"}],
  "reply_variation_palette":{"understanding":["string"],"concern":["string"],"doctor_bridge":["string"],"closing":["string"]}
}
```

`dialogue_rhythm` 只能是 `brief_QA`、`concern_led`、`narrative_then_QA`、`explanation_led`；`speaker` 只能是 `患者` 或 `医生`；`length_target` 只能是 `very_short`、`short`、`medium`。五个及以上实质轮时，`persona_realization_targets.patient` 与 `.doctor` 都不可为空，且每项都必须能对应至少一个 `turn_plan.spoken_candidates`。

## 正例：长建议拆开，而不是念清单

对含“少辛辣、别抽烟喝酒、别久坐熬夜、多运动、放松、温水坐浴”的 Brief，可规划：

```json
{
  "dialogue_rhythm":"explanation_led",
  "turn_plan":[
    {"id":"T1","speaker":"医生","communicative_action":"先给生活节奏建议","clinical_constraint_ids":["C7","C8"],"length_target":"short","spoken_candidates":["轻微词块重复"],"must_avoid":["一次列出所有建议"]},
    {"id":"T2","speaker":"患者","communicative_action":"接住前一句","clinical_constraint_ids":[],"length_target":"very_short","spoken_candidates":["多样短确认"],"must_avoid":["新增病例反馈"]},
    {"id":"T3","speaker":"医生","communicative_action":"补充久坐熬夜与运动","clinical_constraint_ids":["C9","C10"],"length_target":"short","spoken_candidates":["省略表达"],"must_avoid":["新风险解释"]},
    {"id":"T4","speaker":"医生","communicative_action":"给出原有缓解措施","clinical_constraint_ids":["C11"],"length_target":"short","spoken_candidates":["术语轻重启可选"],"must_avoid":["补充疗效承诺"]}
  ],
  "persona_realization_targets":{"patient":["接住建议时用生活化短确认，不固定说好"],"doctor":["建议开头的轻重复","一句省略式承接"]},
  "coverage":[{"constraint_id":"C7","turn_ids":["T1"]},{"constraint_id":"C8","turn_ids":["T1"]},{"constraint_id":"C9","turn_ids":["T3"]},{"constraint_id":"C10","turn_ids":["T3"]},{"constraint_id":"C11","turn_ids":["T4"]}],
  "long_turn_splits":[{"constraint_ids":["C7","C8","C9","C10","C11"],"split_strategy":"拆成三段医生建议，中间放不含临床新信息的患者承接","permitted_bridge":"听懂后的短确认"}],
  "reply_variation_palette":{"understanding":["行","这样啊","对对"],"concern":["那这个咋弄","那我先怎么做"],"doctor_bridge":["嗯，先别急","我知道了"],"closing":["那行，麻烦您了","成，我先这样"]}
}
```

<!-- STAGE: stage4_surface_generation -->
# Stage 4：Surface Generation

根据 Clinical Brief、导演和表演计划，写一段**全新**的真实线下门诊中文转录。你的输入不含原始线上对话；不能试图恢复它的措辞或顺序。

## 生成要求

1. 逐项表达所有 `must_surface`，不新增任何病例/临床信息；`may_merge` 可合并但不能消失。
2. 像录音转写，不像对话剧、病历、公众号、科普或小说。若一句放到病历里仍过于完美，优先拆短、换日常语、用事实允许的接话或省略打断它。
3. 单轮通常八至三十字，硬上限四十字。长叙述、药物清单、预防建议、治疗方案和复合提问都应拆开；只能加入无医学信息的回应，或引出已知 constraint 的问话。
4. **必须执行** `persona_realization_targets`：它们不是可选风格词。每个被选中的人设习惯至少在一处可见地落到文字上；无论患者还是医生，都要能从不看人设 JSON 的成品中辨认出这次的说话方式。可有
   1. “就就”“没……没”“但是但是”“过敏……过敏原”“这个……”；
   2. 倒装如“要忌很久吗这个？/能查吗这个？/怎么弄啊现在？”等等，实际上倒装句式非常多样，你可以参照广东人口语的句式；
   3. 不完整句如“以前有过。后来又来了。”；
   4. 以及“应该大概是这样？”等局部语法。也可以保留干净轮次。
5. 口癖要像局部稳定的个人习惯，不是随机装饰。比如同一患者在组织话时反复出现“这个”或把焦点放句尾；同一医生常用“是吧/哈”收短、先 echo 再回答，或在技术词前短重启。不要每轮都同一个口癖；不要因为是医生就删掉其嘴飘、卡壳、倒装或俚语。
6. 口误/嘴瓢可以不修正，只要上下文能唯一还原原有医学含义；不能先说一个相反的医学事实再撤回。无意义“呃不是”不是自然度的来源。
7. 短回复须随功能变化。可用“行、成、哦、这样啊、对对、明白了、那我懂了、那先这样、麻烦您了”；不要连续堆“好、嗯好、知道了”。
8. 没有括号动作；不用阿拉伯数字；不残留线上动作。人物可以自由，但不可编造职业、身份、病史或心理事实。
9. 可以通过回应、赞同等等，增强两人的互动性，患者极少怀疑或不相信医生的指导和解释。
10. **注意**上下文问题，比如先前一方完全没有提到某个现状、药物、情况，那么接下来对方就不能直接讲述相关内容。你需要假设两人先前完全不认识不了解。
    1.  但是医生可以阅读病人病历，先前医生可以说明查看病历的请求，然后之后表达从病历阅读到某些信息。
    2.  或者其他可以了解病人既往病史、生活习惯和治疗方案等的方法。

## 输入

```json
{"output_identity":{"dialogue_id":0,"source":"","meta":{}},"clinical_brief":{...},"encounter_director":{...},"spoken_performance_plan":{...}}
```

修复时会额外输入 `repair_mode`、`previous_dialogue` 和 `repair_targets`。只修指定问题及必要的相邻衔接，不重新引入新内容。

## 输出（唯一最终格式）

```json
{"dialogue_id":0,"source":"","meta":{"sex":null,"age":null,"language":"Chinese"},"dialogue":[{"speaker":"患者","text":"string"}]}
```

`meta.sex` 只能为 `男`、`女` 或 `null`；`meta.age` 只能为非负整数或 `null`；`meta.language` 只能为 `Chinese` 或 `null`。每个 `dialogue` 项的 `speaker` 只能为 `患者` 或 `医生`；`text` 必须是字符串。

## 完整正例一：同一临床约束，明显不同于线上问答

基于上面的荨麻疹 Brief，以下可接受：

```json
{"dialogue_id":883,"source":"","meta":{"sex":"女","age":21,"language":"Chinese"},"dialogue":[
  {"speaker":"医生","text":"你好，坐。今天主要问啥？"},
  {"speaker":"患者","text":"我慢性荨麻疹，这个……吃东西是不是得老忌着？"},
  {"speaker":"医生","text":"你担心忌口这块。过敏原查过没有？"},
  {"speaker":"患者","text":"没……没查过。"},
  {"speaker":"患者","text":"那能查吗这个？"},
  {"speaker":"医生","text":"能，过敏……过敏原可以查。"},
  {"speaker":"患者","text":"要是查着了，是不是就得忌一辈子？"},
  {"speaker":"医生","text":"不用这么想，体质会变的，不是永远忌。"},
  {"speaker":"患者","text":"哦，这样啊。那我懂了，麻烦您。"}
]}
```

这里有起句填充、否定重复、倒装、医生术语重启和不同功能的短回应；没有添加食物、皮疹频率、检查细节或新建议。

### 人设—表面实现对照（必须学习这种对应，而非照抄句子）

| 已抽到的人设习惯 | 可见的转写实现 |
| --- | --- |
| 患者“焦点放句尾” | `那能查吗这个？`、`得忌很久吗？` |
| 患者“主诉时词块重复” | `我这个、我这个慢性荨麻疹……`、`就就怕一直忌。` |
| 医生“先 echo” | `忌口这块啊……`、`没查过是吧？` |
| 医生“术语检索/轻重启” | `过敏……过敏原能查。` |
| 医生“短尾口癖” | `可以的哈。`、`先这样，是吧。` |

同一 turn 也能叠加两个现象：`这个……我我以前有过，应该大概是这样？`。是否使用由当句压力和人设决定，不得变成每句都破碎。

## 完整正例二：把长生活建议表演成短门诊轮次

如果 Brief 已明确包含慢性前列腺炎、尿不尽、偶尔尿痛且不经常、近期未吃药，以及前述全部生活建议和“可用沙巴棕胶囊”，一种可接受结果为：

```json
{"dialogue_id":588,"source":"","meta":{"sex":"男","age":28,"language":"Chinese"},"dialogue":[
  {"speaker":"医生","text":"你好。这个老毛病以前看过？"},
  {"speaker":"患者","text":"看过，说是慢性前列腺炎。"},
  {"speaker":"医生","text":"现在主要还是尿不尽？"},
  {"speaker":"患者","text":"对，上厕所老感觉没完。有时候有点痛，不过不常痛。"},
  {"speaker":"医生","text":"最近自己吃药没有？"},
  {"speaker":"患者","text":"没，最近没吃。"},
  {"speaker":"医生","text":"平时规律点，规律生活。辛辣先少碰。"},
  {"speaker":"患者","text":"行，我记着。"},
  {"speaker":"医生","text":"烟酒别沾，久坐熬夜也尽量别来。"},
  {"speaker":"患者","text":"嗯，这些确实得改。"},
  {"speaker":"医生","text":"多动一动，心态放松些。温水坐浴也可以做。"},
  {"speaker":"患者","text":"那药呢，有用吗这个？"},
  {"speaker":"医生","text":"沙巴棕胶囊，可以吃点看看。"},
  {"speaker":"患者","text":"成，谢了医生。"}
]}
```

药名保持清楚；“规律点，规律生活”是可理解的轻重复；所有预防、缓解和药物事实均保留，未新增疗效或复查安排。

## 真实转录风格观察库（只学现象，不迁移病情）

以下是用户提供的真实转录片段。它们不是强制模板，更不能把其中的疾病、检查、药物或追问挪到新病例。

```text
医生：没有是吧？当时有没有看呢？
患者：当时没看。
医生：没没看，然后怎么样就好了呢？
患者：休息休息，一下午加一晚上，我请假休息后第二天就好了。
医生：行。呃，最近有再发发吗？
患者：最近就就这段时间，有有个把星期吧。
```

观察：echo、词块重复和嘴飘发生在确认与回忆，分布并不均匀。

```text
患者：就一开始我就是感觉在上班的时候胀痛胀痛的，然后一直冒冷汗，我就……就过来了。
患者：以前有过，但是到到输到那个输尿……输尿管里面就，我去检查，他说可以排出来。
医生：皮皮脂。
患者：就那个什么。
医生：皮脂腺囊肿。
```

观察：较重的卡壳集中在突发经历回忆和词汇检索；术语最终被还原。短咨询完全不必复制这种密度。

## 反例：不要写成“医学正确的作文”或“固定口误表演”

坏（太书面）：`考虑到您的体质存在变化，因此并不需要终身严格忌口。`

好（相同医学含义）：`不用一直忌，体质会变。`

坏（硬塞自我修正）：`你必须永远忌口，呃不是，也许不用。`

好（自然、意义稳定）：`查到了也不等于得一直忌。`

<!-- STAGE: stage4_surface_repair -->
# Stage 4：Surface Repair

沿用 Surface Generation 的全部边界。根据 `repair_targets` 做最小、定点修复；保留未被点名的有效轮次。不得因修复而加入任何病例或医学信息，也不得重新设计整段对话。

## 输入

```json
{"output_identity":{...},"clinical_brief":{...},"encounter_director":{...},"spoken_performance_plan":{...},"repair_mode":true,"previous_dialogue":{...},"repair_targets":[{"action":"rewrite_turn","turn_index":0,"instruction":"string"}]}
```

## 输出

与 Surface Generation 的最终格式完全相同。

## 正例

若目标指出“药名内部无动机断裂”，把 `沙巴棕……沙巴棕胶囊` 改为 `沙巴棕胶囊，可以吃点看看`；不要顺带加入别的药、剂量、疗程或解释。

<!-- STAGE: stage5_clinical_naturalness_judge -->
# Stage 5：Clinical / Naturalness Judge

审查生成对话。优先守住所有临床约束，同时阻止文绉绉、逐句改写、机械短回复、过度表演和不合理线下内容。不要因为顺序变化、措辞变化、医生/患者都有卡壳，或存在正常口语语法而误判。

## 输入

```json
{"generated_dialogue":{...},"clinical_brief":{...},"encounter_director":{...},"spoken_performance_plan":{...}}
```

## 输出

```json
{
  "verdict":"pass",
  "checks":[
    {"rule":"constraint_coverage","pass":true,"violations":["string"]},
    {"rule":"clinical_fidelity_and_modality","pass":true,"violations":["string"]},
    {"rule":"no_synthetic_case_detail","pass":true,"violations":["string"]},
    {"rule":"offline_realism","pass":true,"violations":["string"]},
    {"rule":"persona_realization","pass":true,"violations":["string"]},
    {"rule":"spoken_naturalness","pass":true,"violations":["string"]},
    {"rule":"short_turn_rhythm","pass":true,"violations":["string"]},
    {"rule":"short_reply_variation","pass":true,"violations":["string"]},
    {"rule":"format","pass":true,"violations":["string"]}
  ],
  "repair_targets":[{"action":"rewrite_turn","turn_index":0,"instruction":"string"}]
}
```

`verdict` 只能是 `pass` 或 `repair`。`repair_targets` 在 `pass` 时应为 `[]`；在 `repair` 时 `action` 只能是 `rewrite_turn`、`split_turn`、`merge_turn`、`insert_turn`、`remove_turn`、`move_turn`。

## 判定细则

- `constraint_coverage`：所有 `must_surface` 均表达；药物、治疗、缓解、预防、忌口、生活方式、随访等都在范围内。合并重复可以，漏掉不行。
- `clinical_fidelity_and_modality`：不新增/反转/强化医学信息；患者不替医生下新结论；“可以/考虑/不一定”保留原力度。
- `no_synthetic_case_detail`：不允许新增患者症状、时间、诱因、检查、结果、经历、疗效或回答。
- `offline_realism`：无上传、在线、照片、平台等远程行为；但不得误删本来属于症状发生经过的地点/时间背景。
- `persona_realization`：逐项检查 Stage 3 的 `persona_realization_targets`。目标中的每个习惯必须在对应角色至少一个具体 turn 可见；不能只在 JSON 里存在、成品却是两位同一种书面口吻的人。若缺失，指定最适合的现有 turn 以最小改写落实它。
- `spoken_naturalness`：五个以上实质轮若除了“嗯/哦”没有任何自然的倒装、省略、重启、重复、检索、echo、词序变化或口语表达，应修复；整段还必须至少有三处非纯语气词的口语结构、至少一处倒装/词块重复/起句重启/术语检索/省略/词序不完整。若每句都“呃不是”、每处术语都故意断裂、像文学台词，也应修复。无需两人平均分配瑕疵。
- `short_turn_rhythm`：超过约三十五字且含多个事实组的轮次应拆；插入轮必须不携带新临床信息。相邻说话人不可相同。
- `short_reply_variation`：相邻三次短确认不应机械重复同一“好/嗯好/知道了”。
- `format`：最终 object、speaker、中文 text、中文数字、无动作括号、无单轮超过六十字均正确。

修复目标必须具体、最小化，例如“第六轮将两项生活建议拆开，插入不带医疗信息的承接”，不能写“再加两处结巴”。

## 正例

若五个以上实质轮全是完整书面句，且没有任何可听见的口语结构，输出 `repair`，目标可为：`{"action":"rewrite_turn","turn_index":4,"instruction":"在不改临床含义的前提下改为自然倒装或省略表达；不要仅加嗯。"}`。若医生的人设目标是“先 echo 患者关键词”，却一处也没有 echo，则目标可为：`{"action":"rewrite_turn","turn_index":3,"instruction":"用不新增信息的半句 echo 接住患者刚说的担心，再保留原有医学回应。"}`。