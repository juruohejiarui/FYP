# 临床约束 → 线下门诊 → 真实转录

## 总目标与分层

任务不是把线上问答逐句改口语，而是以原内容中可靠的临床知识和病例约束为素材，重新导演一次可信的医院门诊部真实发生的线下门诊，再把它写成未经剧本打磨的录音转写。

工作链路固定为：

> 原始线上文本 → Clinical Brief → Encounter Director → Spoken Performance Plan → Spoken Base → Disfluency Plan → 线下面诊转录

保留主问题、症状与病程、已有诊断/检查/药物、医生解释、治疗、缓解、预防、生活方式、忌口、随访和关键否定/条件；不保留原话、原轮次、原句法或原有问答顺序。

### 绝不允许的事

- 不新增患者病例细节：不能补症状、病程、诱因、检查结果、既往史、用药史、过敏史、孕育状态或疗效。也不能为了让医生能问诊而让患者凭空回答。
- 不新增、不替换、不夸大医学结论、诊断、检查、药物、剂量、治疗、风险、注意事项或安慰性判断。
- 不把「没有、偶尔、考虑、可以、不一定、问是否」说成相反、更重、更频繁、确诊或必须。
- 不把线上特有内容原样搬到线下：上传、发图、语音/视频、平台、在线、刚看到、在开车准备去医院、到正规医院检查等。若「开车时头晕」是症状发生背景，则保留其病史意义。
- 不得照搬原问答顺序或原句法。不得用原文加未锁内容。

### 创作自由与口语标准

在不碰临床约束的前提下，可自由决定开场、谁先说、信息呈现顺序、追问形式、收尾、轮数、口头习惯和对话张力。这里的「真实」不是更通顺，而是更像转写：短、互相接得上、有局部卡顿，但不是整段故意演结巴。

患者和医生都可能出现：重复/结巴、嘴瓢、未修正但可理解的口误、倒装（「有用吗这个？」）、省略、语气词、无意义填充（「这个……」）、局部语法不完整、自我修正、术语检索和 echo。一次发言可有零个或多个现象；它们由人设、信息压力和这一次对话的偶然性驱动，不按每人、每轮、每段配额分派。医生的专业性体现为最终传达的医学含义可靠，不体现为永远流畅。

五个及以上实质轮必须让本次抽取的人设和口语现象可被听见。至少实现三处非纯语气词的口语结构，并至少有一处来自倒装、词块重复、起句重启、术语检索、省略或词序不完整。少于五个实质轮则允许只有零到一处。禁止固定地让每个人各结巴一次。

可自然使用日常说法：肚子、上厕所、尿尿、拉屎、看病、吃药、没啥用、不见好、堵得慌、咋回事、这毛病、反反复复、拖着、得、要不、行、没事儿、挺难受的。口语化不得改变医学语义。

### 输出格式

- Stage 0、Stage 6、Stage 7 输出一个 JSON object。Stage 1–5 输出受控行式文本区块，用固定起止标签。不要 Markdown 解释，不要提前写最终 JSON。
- 行式字段名大写。列表用 `- ` 开头。空列表写 `- none`。不确定就省略该字段，不要填「未知」。
- Stage 0 只补全 meta。Stage 1–5 只供后续使用。Stage 6 的 object 是最终对话。Stage 7 不写入最终文件。
- 最终 `text` 不用阿拉伯数字、括号动作说明或线上平台词。数字改为自然中文说法。优先交替说话人；同一人连续实质轮最多 2，第 3 条实质前必须有对方短回应。

### 约束编号

`C1`、`C2` 是 Stage 1 给每一条临床约束起的短编号，类似病历条目号。后段用编号引用，避免把整句约束抄来抄去。`C1` 起于 Brief 的 CONSTRAINTS 行；后段只能引用已有编号，不得另起。

### 单点一轮与承上启下

一轮默认只承载**一条**实质：一个问题，或一个短答，或一条建议，或一种药，或一个征象，或一个解释。计划行只能挂**一个**约束编号，或回应轮写 `none`。半句 echo（2–6 字）不算第二条，允许「半句接住 + 推进」且 ≤ 二十。同一条约束的「短答 + 极短限定」才可同轮，不得把两条独立约束焊在一轮。SETS 组成员各说一轮，中间插对方 `嗯`/`对`，禁止收成「注意生活」。

- **承上**：对方刚说完实质，本轮优先带上一轮已出口的 2–4 字，或 `对` / `哦这样`，再问、答或给下一条。不要光秃秃 `嗯` 就换无关主题。清单第二条前单独 `嗯`/`对` 仍够。
- **启下**：半句 echo 不得单独占一轮后停住；字数够则同轮接上问/答/建议（`夜里口干，查过没有？`）；拆轮后自己下一轮必须推进。禁止整句回读和「你是问能不能查」类元复述。
- **回应问句**：上一轮是患者问句时，医生首个实质轮必须答、澄清、为答而追问，或先收住再换题。不能把无关约束直接当答案。

### 事实飘移四问

后段不问「意思是否差不多」。每条 `must_surface` 约束只核 `keep` / `when` / `tense` / `must_not`：

1. 听完这句，会不会多出 C 没说过的事？（会 → 飘移）
2. `keep` 和 `when` 还能听见吗？隔开很多轮只剩光杆症状，算听不见（不能 → 削平）
3. 力度还是不是原来的？（可以→必须、偶尔→经常、问是否→已结论 → 飘移）
4. 时态还是不是原来的？（以前有过→现在还有、最近没吃→一直不吃、做过已停→正在做、打算查→已经查了 → 飘移）

`when` 可以来自更早一轮。实现该 C 时，`when` 必须出现在本轮或邻轮。`tense` 必须从原词读出，不得按病种常理推断。

### 错字漏字

见原文时先按上下文认意图，再锁校正后的词。不要把乱码锁成新病、新药；看不准就标不确定，不要丢掉整条。台词用校正说法，不复述明显错字当新事实。

## 人设来源库：必须从这里选择，而不是压成「患者/医生都很自然」

- `chronic_self_manager`：患者长期和同一类问题打交道，有一点自我管理语言；可以更快抓住「减量、复发、忌口、检查」这类 Brief 已经出现的词，但仍可能把句子说断、问得很生活化。
- `medical_worker_or_student`：患者懂得一些术语，记忆不清晰，可能用诊断名/检查名反问，或先说半句术语又换成日常词。不能因此补出原 Brief 没有的诊断、检查、疗法或同事意见。
- `researched_layperson`：患者会说「我看了下」「这个是不是……」一类半懂不懂的提问，但只能围绕已知临床约束；若引进网传方案，医生必须用不可信等原因否定。
- `little_medical_knowledge`：患者更多用「这毛病、堵得慌、咋回事」一类日常表达，医生需要把已有结论拆短解释；不是把患者写成低智，也不是强行结巴。
- `very_familiar`：医生用语利落，但也可以有简短 echo、俚语、倒装和轻微嘴飘。
- `ordinary_outpatient_style`：医生是常见门诊表达，边问边接话，常把患者关键词复述一半。
- `less_familiar_with_topic`：医生可能先检索或用更泛的说法，术语/药名可重启；最终只能落回 Brief 已有结论，不能因「不熟」虚构模糊诊断。
- `early_career`：医生解释会略显按步骤、偶尔重复连接词，但不必写成书面教学。
- `tired_but_careful`：医生有「嗯、这个、是吧」、短暂停顿、词序滑动或口误；医学含义仍完整，不能表现为粗暴、漏诊或乱开药。
- `other: 一个自定义的更好的人设描述句子`：允许自创符合真实门诊的人设，只要后续阶段能执行。写法参照上面预设。

无论何种人设：患者极少怀疑或不相信医生的指导和解释。人设不能新增病例事实。

<!-- STAGE: stage0_meta_inference -->
# Stage 0：Meta Inference

仅补全输入 `meta` 中缺失的 `sex`、`age`、`language`。不改写对话，不推断情绪、人设或口语习惯。已有值不改。只有直接证据才推断；证据不足就为 `null`。原始 meta 全空时也必须尝试从首句括注、自称、怀孕/月经等强线索和语种去推导，推不出则 `null`。

## 输入

紧凑 `[SOURCE]`（含 meta 与台词行）。先甄别错字漏字再推断。

## 输出

```json
{"sex":null,"age":null,"language":"Chinese","evidence":"string","confidence":"low"}
```

`sex` 只能为 `男`、`女` 或 `null`；`age` 只能为非负整数或 `null`；`language` 只能为 `Chinese` 或 `null`。`confidence` 只能为 `high`、`medium`、`low`。

## 正例要点

首句「夜里口干 睡不着（男，34岁）」且 meta 全空 → `sex=男` `age=34` `language=Chinese`，`evidence` 写括注。只有「我怀孕了」而无年龄 → `sex=女`，`age=null`。

## 反例

不要因为口干常见于中年男性就猜性别；没有明示就 `null`。不要把「慢性病」映射成焦虑人设。不要因错字「女仕」就放弃括号里的性别。不要输出解释或 Markdown。

<!-- STAGE: stage1_clinical_brief -->
# Stage 1：Clinical Brief

从原始线上内容中抽取所有需要保留的临床约束。不是逐轮账本，不复述原句，也不设计台词。见原文时先按上下文校正错字漏字，再锁校正后的医学意图。

## 抽取规则

每条临床信息都要成为一个独立 constraint，覆盖以下所有相关类别：`reason_for_visit`、`symptom`、`course`、`condition`、`test`、`test_result_or_status`、`medication`、`treatment`、`self_care`、`prevention`、`relief`、`avoidance`、`follow_up`、`doctor_explanation`、`patient_concern`、`negation`、`uncertainty_or_condition`、`other_clinical`。

- 医生给出的生活方式、预防、缓解、忌口、复查、观察等内容和药物一样需要保留，不能因不是「诊断/症状」而漏掉。
- 保留说话人立场、限定词、情境、时态和方向。「偶尔痛」「没查过」「能不能查」「不一定要吃药」「拉肚子的时候手抖」「以前有过」都不能压扁。
- 同义重复可合并；一条原始长句内的多个独立临床点必须拆开。
- `must_surface` 表示最终对话必须以自然方式表达；`may_merge` 只表示可与**同一条**约束的极短限定同轮，不能把两条独立约束焊在一轮。
- `offline_transform_notes` 只记录如何去除线上痕迹，不得创造当面检查或新病史。
- 每条约束必须有编号 `C1`、`C2`…，并写飘移锁：`keep=` `when=` `tense=` `must_not=`。`tense` 只能是 `以前有过` / `现在还有` / `最近没` / `正在` / `做过已停` / `打算` / `none`。无情境写 `when=none`。`tense` 从原词读出，不得按病种常理补成持续状态。
- 一串生活建议、多种药、多个征象必须各锁一条，并写入 `SETS`（如 `set_01 | C7,C8,C9 | lifestyle`）。组成员后段各说一轮，不得收成一条。无此类清单写 `SETS: - none`。
- 过四问。漏写 `keep`/`when`/`tense` 即失败。

## 输入

紧凑 `[SOURCE]`。

## 输出（仅此区块）

```text
[CLINICAL_BRIEF]
ANCHOR: 夜间口干来问能不能查
CONTEXT: 夜里口干 | 没查过甲状腺
CONSTRAINTS:
- C1 | symptom | patient | 夜里口干 | affirmed | must_surface | ev=0 | keep=夜里,口干 | when=夜间 | tense=现在还有 | must_not=白天也口干|一直口干
- C2 | test_result_or_status | patient | 此前未查过甲状腺 | denied | must_surface | ev=1 | keep=没查过,甲状腺 | when=none | tense=以前有过 | must_not=查过甲状腺|现在就是甲亢
- C3 | test | doctor | 可以查甲状腺 | affirmed | must_surface | ev=3 | keep=可以,查 | when=none | tense=none | must_not=必须去查|先开单
- C4 | patient_concern | patient | 问是否一定要吃药 | question | must_surface | ev=2 | keep=问是否,一定,吃药 | when=none | tense=none | must_not=已经在吃药|必须吃药
- C5 | doctor_explanation | doctor | 不一定要吃药 | conditional | must_surface | ev=4 | keep=不一定,吃药 | when=none | tense=none | must_not=必须吃药|以后一定吃
SETS:
- none
BOUNDARIES:
must_not_add: 具体化验值 | 新药名 | 甲状腺功能数字
must_not_strengthen: 不得把可以查说成必须查
must_not_reverse: 不得把不一定吃药改为必须吃药
OFFLINE:
- none | 无线上动作需要处理
PERMISSIONS: reorder=yes | replace_wording=yes | add_nonclinical=yes | add_case_detail=no
[/CLINICAL_BRIEF]
```

`category` 只能是规则中列出的类别之一；`origin` 只能是 `patient`、`doctor`、`both`；极性槽只能是 `affirmed`、`denied`、`question`、`conditional`、`uncertain`；表面要求只能是 `must_surface` 或 `may_merge`。`ev=` 写原文轮下标，可多值如 `ev=0,2`。

## 正例要点

原料含：夜里口干；未查过甲状腺；患者问能不能查、查了是否一定吃药；医生说可以查、不一定要吃药。必须分别编号锁住症状（`when=夜间` `tense=现在还有`）、未查状态（`tense=以前有过`）、可以查（`keep=可以`）、是否必须吃药的担心（`question`）、不一定吃药。

若内容含「蹲下才会晕、拉肚子时手抖了吗、偶尔腿抽但不经常、最近没吃药、少辛辣、少熬夜、温水敷、可以吃点维生素B」，必须逐条编号。少辛辣/少熬夜/温水敷/维生素B 写入 `SETS`，不得焊成一条「注意生活」。蹲下晕写 `when=蹲下时 keep=蹲下,才会`；拉肚子手抖写 `when=拉肚子时`，即使问句和拉肚子隔了一轮；偶尔腿抽写 `keep=偶尔`；最近没吃药写 `tense=最近没`。错字「阿莫西林林」锁 `keep=阿莫西林`，不要锁成另一种药。

## 反例

不要输出 JSON。不要把「偶尔腿抽」压成「腿抽」。不要把一串生活建议焊成一条，也不要漏写 `SETS`。不要把「可以查」锁成「必须查」。不要把「以前查过」锁成「现在就是」。不要把「最近没吃药」锁成「从来不吃」。不要把「拉肚子的时候手抖了吗」锁成无情境的「有手抖」。不要把「阿莫西林林」锁成新药名，也不要因看不懂整条丢掉。不要按病种常理把「以前犯过」补成「现在还在」。不要在本 stage 写 TURN_PLAN 或台词。不要把线上「发个录音听听」锁成线下已经听过。不要漏 `keep`/`when`/`tense`/`must_not`。不要用原文寒暄当临床约束。不要把仅 meta 的年龄/性别锁进 CONSTRAINTS。

<!-- STAGE: stage1_clinical_brief_repair -->
# Stage 1 Repair：Clinical Brief

只修复传入的 `[CLINICAL_BRIEF]`，并只输出一个完整替换后的同名区块。可参照 `[SOURCE]` 核对遗漏、错字和飘移锁，但不得改变原文医学事实或另造病例信息。只执行 `scope=brief` 的 targets。

- 漏写的 `keep`/`when`/`tense` 从原文补回。清单漏写 `SETS` 时补上，不得把多条焊回一条。
- 错字按上下文改成校正词，不要改成另一种病/药。
- 远距情境（拉肚子时手抖）必须补 `when`，不得收成平时手抖。
- 时态从原词读出，不得按常理改成持续状态。
- 未被 target 点名的正确内容保持不变。不要输出计划、台词、JSON 或解释。

## 正例要点

target 写「C3 漏了 keep=可以」→ 补回 `keep=可以`，其它行不动。target 写「手抖缺 when」→ 改成 `when=拉肚子时`。

## 反例

不要重写整份 Brief。不要把「偶尔」补成「经常」。不要输出 Director 或台词。不要用原文加新症状。

<!-- STAGE: stage2_encounter_director -->
# Stage 2：Encounter Director

仅根据 Clinical Brief 导演一场新的线下面诊。不要写最终台词，不要找回或模拟原始措辞。允许大量创意，但不能新增任何临床信息或患者病例细节。可看 `[SOURCE]` 核对漏抽和 `when`/`tense`，不得照搬原轮次。

## 规则

- 选择现实的门诊框架（初诊/复诊/用药咨询/检查咨询/结果解读/不明），设计新的对话弧线。
- 分别捏两个临场人设。人设只能描述互动方式、说话节奏、知识表达方式和口头习惯，不能新增情绪事实、职业事实、疾病事实或诊疗结论。人设标签可以有多个，用 `|` 分割。
- 两人的差别主要是医学解释权，不是「医生永远顺、患者必结巴」。
- 人设可以有非病例来源：患者可设为长期慢病自我管理者、医学相关从业者、医学生、网上做过功课但半懂不懂的人，或几乎没有医疗知识的人；医生可设为对这类病很熟、普通门诊经验型、对该问题不那么熟、刚工作不久，或当班有些疲惫。无论人设如何，最终医学含义仍必须符合 Brief。
- 每个角色必须给出二到四个 `signature_habits`，且两人至少有两个不同的习惯。习惯应具体到可观察形态，例如「担心时把关键词放句尾问：`要吃药吗这个？`」「半句确认后追问：`夜里口干，查过没有？`」。不要只写「自然、焦虑、耐心、口语化」。
- `disfluency_profile` 要说明什么场景下会出现、哪些现象不适合滥用。
- 允许的桥接只是不携带临床新信息的开场、承接、复述、感谢、请坐等。若设计追问，它只能引出 Brief 中已有且将在后续表述的约束。
- SETS 成员必须排成交替短轮，不得导演成一人连念清单。带 `when` 的约束不得导演成无情境清单。过去事件不得导演成现场正在发生。

## 输入

`[CLINICAL_BRIEF]` + `[SOURCE]`。

## 输出（仅此区块）

```text
[ENCOUNTER_DIRECTOR]
VISIT_FRAME: test_consultation
PREMISE: 患者因夜里口干来问能不能查
ARC:
- 患者先说夜里口干
- 医生问查过没有
- 患者确认没查过并问能不能查
- 医生说可以查、不一定要吃药
- 患者短句收尾
PERSONA_P: source=chronic_self_manager | style=先绕着吃药开口，关键处把词放句尾 | literacy=mixed
HABITS_P:
- 主诉开头偶尔重复词块，如我这、我这个
- 担心时把问题倒装到句尾，如要吃药吗这个
LEX_P: 这个 | 得 | 咋 | 哦这样啊
DISFLUENCY_P: likely: 刚说主诉,追问吃药 | forms: 起句重启,词块重复,倒装 | avoid: 每轮都加省略号
PERSONA_D: source=tired_but_careful | style=接话快，偶尔先 echo 再解释 | literacy=professional
HABITS_D:
- 用半句 echo 接话，如口干这块啊
- 术语前偶尔轻重启
LEX_D: 嗯 | 这块 | 是吧 | 哈
DISFLUENCY_D: likely: 接住担心,提到检查名 | forms: echo,术语重启,短承接 | avoid: 把结论说断到无法理解
BRIDGES:
- 门诊开场 | clinical=no
- 请患者确认此前是否检查 | clinical=no
PRESENT:
- C2 | 用医生确认或患者回忆自然带出
- C5 | 分成一句解释和一句自然收尾
FORBIDDEN:
- 具体化验值
- 新的口干频率
[/ENCOUNTER_DIRECTOR]
```

`VISIT_FRAME` 只能是 `initial_consultation`、`follow_up`、`medication_consultation`、`test_consultation`、`results_discussion`、`unclear`。患者 `literacy` 只能是 `low`、`mixed`、`familiar`，医生固定为 `professional`。`source` 从人设库选。每名角色 HABITS 二至四项，LEX 二至五项。

## 正例要点

同一口干 Brief 可导演成检查咨询：患者先问吃药，医生用未查状态把话题落到甲状腺，再回答可以查、不一定吃药。HABITS 必须可观察。带 `when=夜间` 的口干不要排成白天也干。`tense=以前有过` 的未查不要排成现场刚查完。

## 反例

不要写逐句台词。不要 HABITS 只写「自然 / 耐心」。不要把「可以查」导演成必须开单。不要把 SETS 导演成一人连念。不要把「拉肚子时手抖」排成隔很远才问「有手抖吗」。不要把「最近没吃药」导演成「一直不吃」。不要用 `[SOURCE]` 抄原问答顺序。不要档案与人设打架。不要新增具体食物禁忌或新检查结果。不要安排点名性别或开场自报年龄。

<!-- STAGE: stage2_encounter_director_repair -->
# Stage 2 Repair：Encounter Director

只修复传入的 `[ENCOUNTER_DIRECTOR]`，并只输出一个完整替换后的同名区块。只执行 `scope=director` 的 targets。可看 Brief 与 `[SOURCE]` 核对，不得加病例内容，不得写台词。

- HABITS 至少一条必须是可观察接话方式（半句确认后追问、短答再补）。
- SETS 不得导演成一人连念。带 `when` 的约束不得排成无情境；过去事件不得改成现场正在发生。
- 未被点名的正确导演保持不变。不要输出 JSON 或解释。

## 正例要点

target 写「HABITS 太抽象」→ 改成半句 echo 后追问这类可见习惯。target 写「手抖被排成平时」→ 把该节点改回拉肚子情境。

## 反例

不要重写整场弧线。不要照抄原文顺序。不要把可以改成必须。

<!-- STAGE: stage3_spoken_performance_plan -->
# Stage 3：Spoken Performance Plan

把导演意图转成可表演的短轮骨架。规划交流动作、约束覆盖、长句切分和可选口语现象，不写最后台词。可看 `[SOURCE]` 核对覆盖与 `when`/`tense`，不得照搬原序。

## 规则

- 每个约束编号必须存在于 Brief。所有 `must_surface` 都要在 `COVERAGE` 中出现。SETS 每个成员单独占一行。
- `persona_source` 必须真实影响计划：慢病自我管理者可让已有术语更早出现；医疗知识较少者可让同一事实先以生活话出现。
- 可完全重排约束；一个医学问题不要隔很多轮才回答，除非中间是引出已有事实的必要确认。
- 一轮只推进**一条**实质。计划行只挂一个约束编号，或回应轮写 `none`。半句 echo 不算第二条。
- 优先交替。同一人连续实质轮最多 2；第 3 条实质前必须插入对方短回应。不为交替空造过渡轮。SETS 用交替交付，禁止一人连发整组。
- 每行必须写 `reacts_to=`：指向被接住的上一行 `T1`，无接应写 `none`，不得假装在答。
- 对方刚说完实质，本行优先承上（2–4 字已出口词或 `对` / `哦这样`）再启下。`echo_then_probe` 不得空转停住。
- 上一轮是患者问句时，医生首个实质行必须 `answer`、澄清、为答而追问，或 `topic_shift`。不能把无关约束直接当答案。
- 常用 `act`：`present` / `answer` / `echo_then_probe` / `pure_backchannel` / `acknowledgement` / `topic_shift`。
- 多个建议、治疗、药物或较长内容时主动拆轮。不能添加会逼出新病例信息的开放问题。
- 症状询问时，不要在对方完全没提过该症状时用猜测/确认去套，如直接问「昨天是不是疼得更勤」。
- 五个及以上实质轮时，必须从 Stage 2 两人 HABITS 中各挑出一至三个本次要实现的习惯，写进 `PERSONA_TARGETS`。整段至少计划三处非纯语气词的口语结构，其中至少一处为倒装、词块重复、起句重启、术语检索、省略或词序不完整。
- 带 `when` 的约束必须与情境锚点相邻；若必须分开，实现轮要把 `when` 再说一遍。不得把过去事件排成现场正在发生。
- 假设两人先前不认识。医生若要用病历信息，须先安排查看病历的请求。

## 输入

Brief + Director + `[SOURCE]`。

## 输出（仅此区块）

```text
[SPOKEN_PERFORMANCE_PLAN]
RHYTHM: explanation_led
PERSONA_TARGETS:
- patient | 接住建议时用生活化短确认，不固定说好
- doctor | 半句确认后追问
[TURN_PLAN]
T1 | 医生 | present | C7 | reacts_to=none | short | 轻微词块重复 | 一次列出所有建议
T2 | 患者 | pure_backchannel | none | reacts_to=T1 | very_short | 嗯或对 | 偷渡新事实
T3 | 医生 | echo_then_probe | C8 | reacts_to=T2 | short | 半句确认后再给下一条 | 整句回读后停住
T4 | 患者 | acknowledgement | none | reacts_to=T3 | very_short | 哦这样 | 新增病例反馈
T5 | 医生 | present | C9 | reacts_to=T4 | short | 术语轻重启可选 | 补充疗效承诺
[/TURN_PLAN]
COVERAGE:
- C7 | T1
- C8 | T3
- C9 | T5
SPLITS:
- C7,C8,C9 | SETS 成员各一轮，中间放患者短确认 | 听懂后的短确认
PALETTE:
understanding: 行 | 这样啊 | 对对
concern: 那这个咋弄 | 那我先怎么做
doctor_bridge: 嗯先别急 | 我知道了
closing: 那行麻烦您了 | 成我先这样
[/SPOKEN_PERFORMANCE_PLAN]
```

`RHYTHM` 只能是 `brief_QA`、`concern_led`、`narrative_then_QA`、`explanation_led`。说话人只能是 `患者` 或 `医生`。长度只能是 `very_short`、`short`、`medium`。五个及以上实质轮时 PATIENT/DOCTOR 的 PERSONA_TARGETS 都不可为空。TURN 行格式：`Tid | 说话人 | act | 约束编号或none | reacts_to=Tid或none | 长度 | 口语候选 | 必须避免`。

## 正例要点

一串生活建议必须拆轮，中间插患者短确认。医生接患者「夜里老口干」应写成 `echo_then_probe`：`夜里口干，查过没有？` 患者问「能查吗这个？」后医生首个实质行必须答「可以查」，不能改口说少熬夜。`when=拉肚子时` 的手抖问句必须紧挨拉肚子，或问句里再说「拉肚子那阵」。`tense=最近没` 的药安排成「这阵子没吃」，不要排成「从来不吃」。

## 反例

不要写最后台词。不要一行挂两个约束编号。不要把 SETS 三成员焊进一轮。不要同一人连续第 3 条实质无人接。不要光秃秃 `嗯` 后换无关主题。不要 echo 整句回读后停住。不要患者问能不能查、医生用少熬夜当答案。不要把带 `when` 的约束和情境锚点中间夹许多无关轮。不要隔开后只排「有手抖吗」。不要把「以前有过」排成「现在还这样」。不要医生在患者没提过该症状时套「是不是更勤了」。不要 HABITS 目标为空却有五个以上实质轮。不要安排点名性别或无依据自报年龄。不要用 `[SOURCE]` 抄原序。不要添加会逼出新病史的开放问。

<!-- STAGE: stage3_spoken_performance_plan_repair -->
# Stage 3 Repair：Spoken Performance Plan

只修复传入的 `[SPOKEN_PERFORMANCE_PLAN]`，并只输出一个完整替换后的同名区块。只执行 `scope=plan` 的 targets。严格实现 Brief 与 Director。不写台词。

- 漏掉的 `must_surface` 必须补进 TURN_PLAN 与 COVERAGE。SETS 成员必须各占一行。
- 一行只挂一个约束编号。同一人连续实质超过 2 时插入对方短回应。
- 缺 `reacts_to`、问句后用无关约束当答案、echo 空转，按承上启下改回。
- 带 `when` 的行必须与情境相邻，或在该行重提 `when`。
- 过去事件不得改成现场正在发生。
- 未被点名的正确计划保持不变。不要输出 JSON 或解释。

## 正例要点

target 写「C4 未覆盖」→ 加一轮患者问是否一定吃药。target 写「手抖离拉肚子太远」→ 把两行挪到相邻，或让问句带「拉肚子那阵」。target 写「医生连说三条建议」→ 在第 2 条后插入患者 `嗯`。

## 反例

不要写逐句台词。不要借修复加新约束编号。不要把可以改成必须。不要把两行焊回一行来「省轮」。

<!-- STAGE: stage4_spoken_base -->
# Stage 4：Spoken Base

生成已经像线下门诊、但不刻意添加失流的自然口语底稿。严格实现 TURN_PLAN。底稿是短句接话，不是讲稿。每句台词优先 ≤ 二十汉字，为失流预留余量。不得出现 `：` `；`，不得用阿拉伯数字。

编号从 `1` 开始与 TURN_PLAN 对齐：

```text
<行号> | <说话人> | <Tid> | <约束编号或none> | reacts_to=<Tid或none> | <台词>
```

- 主源是 Brief + Director + Plan。`[SOURCE]` 只在某条已许可约束写不准或含糊时用来校准措辞。契约已写清且准确时不要抄原文。
- 不得用原文加新约束编号、未锁内容或未激活主题。不得照搬原轮次、原句法、原问答顺序。
- 台词用校正后的说法，不复述明显错字。
- 对所挂约束过四问。`when` 必须在本轮或邻轮听得见。`tense` 必须保持。
- 一轮只说一条实质。半句 echo + 推进可以同轮。SETS 成员不得焊进一句。
- 未激活内容不能点名套问。中性开放问可以是「还有别的不舒服吗」「这次主要想问什么」。
- **承上**：接对方实质时带 2–4 字已出口词或 `对` / `哦这样`。清单第二条前单独 `嗯` 即可。
- **启下**：echo 默认 2–6 字，禁止整句回读；同轮或自己下一轮必须推进。
- **回应问句**：上一轮是患者问句时，本轮必须答、澄清、为答而追问，或先收住再换题。`reacts_to` 必须指向被接住的那一行。
- 同一人连续实质台词最多 2 条；第 3 条前必须有对方短回应。
- 不得问或念性别；不得问年龄；无锁定年龄不得自报。
- 不得把医生建议写成患者已经在做或以后一定做。

## 输入

Brief + Director + Plan + `[SOURCE]`。

## 输出（仅此区块）

```text
[SPOKEN_BASE]
1 | 患者 | T1 | C1 | reacts_to=none | 夜里老口干。
2 | 医生 | T2 | C2 | reacts_to=T1 | 夜里口干，查过没有？
3 | 患者 | T3 | C2 | reacts_to=T2 | 没查过。
4 | 患者 | T4 | C4 | reacts_to=T2 | 能查吗这个？
5 | 医生 | T5 | C3 | reacts_to=T4 | 可以查。
6 | 患者 | T6 | none | reacts_to=T5 | 哦。
7 | 医生 | T7 | C5 | reacts_to=T6 | 不一定要吃药。
8 | 患者 | T8 | none | reacts_to=T7 | 这样啊，行。
[/SPOKEN_BASE]
```

## 正例要点

`keep=偶尔` → 「偶尔腿抽一下」。`when=拉肚子时` → 「拉肚子那阵手抖了吗」，邻轮还能听见拉肚子。`tense=最近没` → 「这阵子药没吃」。`keep=可以` → 「这个检查可以做」。错字原文「阿莫西林林」→ 「阿莫西林」。患者说「夜里老口干」后医生「夜里口干，查过没有？」；患者问「能查吗这个？」后医生「可以查」，不能改口说少熬夜。少辛辣 / 少熬夜 中间插「嗯」。

## 反例

不要在 Base 里堆显式失流。不要「偶尔腿抽」说成「腿一直抽」。不要「可以查」说成「得去做」。不要「拉肚子那阵手抖」隔开后只问「有手抖吗」。不要「以前犯过」说成「现在还这样」。不要「最近没吃」说成「从来不吃」。不要契约已写清时整句抄 `[SOURCE]`。不要用原文加未锁症状或照搬原问答顺序。不要复述「阿莫西林林」当新药。不要单轮超二十还接着写。不要一轮三条建议。不要同一人连说第三条实质内容。不要光秃秃 `嗯` 后换无关主题。不要 echo 后停住。不要患者问能不能查、医生答少熬夜。不要 `请先说下年龄和性别`。不要把医生建议说成「我平时已经少吃辣了」。

<!-- STAGE: stage4_spoken_base_repair -->
# Stage 4 Repair：Spoken Base

只修复传入的 `[SPOKEN_BASE]`，并只输出一个完整替换后的同名区块。只执行 `scope=spoken_base` 的 targets。严格实现 Brief 与 Plan。

- 修复遗漏时只能补回 Brief 已锁、Plan 已许可的约束编号。
- 四问失败的台词按 `keep`/`when`/`tense`/`must_not` 改回；必要时在本轮或邻轮补回 `when` 词。
- 一轮多点、无承上换题、问句答非所问、同一人连续第 3 条实质，按计划改回。
- `[SOURCE]` 仅在已许可约束写不准或含糊时用来校准该轮措辞。
- 不得用原文加新约束或未锁内容；不得照搬原轮次。不加失流、不输出 JSON 或解释。

## 正例要点

target 写「C6 听成平时手抖」→ 改回「拉肚子那阵手抖了吗」。target 写「可以写成必须」→ 改回「可以查」。

## 反例

不要把未锁寒暄补进底稿。不要借修复加新症状。不要把过去改成现在。

<!-- STAGE: stage5_disfluency_plan -->
# Stage 5：Disfluency Plan

你是失流计划器。你只能为 Spoken Base 的每一行规划局部失流和口语句法；不得改写、复述或输出 Spoken Base，也不得输出最终对话，不得再输出人物小传。输入不含原文。

优先落在：回忆、纠正、术语检索、改话题、高压力解释。不要把省略号只堆在结论/术语前当作拆分的替代。打断残句不得切在药名、剂量、时间、否定、诊断中间。

不要连续多轮人人失流。`none` 不得与事件同行。偏置来自 Director 的 `DISFLUENCY_*` 与 Plan 的 `PERSONA_TARGETS`。

规则：

- 每轮默认 0–2 个失流事件；短答 0–1 个；医生通常 0–1 个。
- 实现后该轮汉字数仍须 ≤ 四十。底稿已 ≥ 三十五时本轮写 `none`，或只加一个极短填充。
- 失流可以碰到医学锚点，但除可理解俗称/口误外，同一轮必须纠正到 Spoken Base / 该行约束的正确表达。
- `self_repair` 的 correct anchor 必须是最终正确且受 Brief 锁定的表达。
- `slip` 仅当对方能完全理解成同一锁定实体时才可不跟 `self_repair`。若会变成另一种药、另一种病、错误剂量或错误时长，必须纠正或不要用 slip。
- 失流只可对同一行 Spoken Base 已许可的文字做停顿、重复、重启或当场修正；不得借事件新引入 Brief 没有的主题词。
- 不加入咳嗽、笑声、叹气、动作、背景声。
- `oral_syntax` 最多一个。`none` 与其他事件不可同一行出现。
- 失流不得削平 `keep`/`when`/`tense`。

## 输入

Brief + Director + Plan + Spoken Base。

## 输出格式

```text
<Spoken Base 行号> | <事件>; <事件>; <口语句法>
```

```text
[DISFLUENCY_PLAN]
1 | oral_syntax(topic_fronting)
2 | none
3 | filled_pause(start, "嗯"); self_repair("两周" <- "十来天", "不对")
4 | none
5 | restart(start, "这个，呃")
6 | none
7 | none
8 | none
[/DISFLUENCY_PLAN]
```

### 事件

| 事件 | 格式 | 含义 |
| --- | --- | --- |
| `filled_pause` | `filled_pause(position, "text")` | 插入可转录填充词 |
| `discourse_marker` | `discourse_marker(position, "text")` | 弱语篇词，如「就是」「其实」 |
| `silent_pause` | `silent_pause(position, "anchor", level)` | 在指定位置加停顿，最终统一 `……` |
| `repetition` | `repetition("anchor", count)` | 将 anchor 额外重复 count 次再保留原 anchor |
| `restart` | `restart(position, "abandoned text")` | 先说不完整起句，再回到原句 |
| `self_repair` | `self_repair("correct anchor" <- "reparandum", "cue")` | 先说错/不准 + 修正提示 + 正确表达 |
| `prolongation` | `prolongation("anchor", level)` | 对非关键医学结论的词作轻微拉长 |
| `slip` | `slip("correct anchor", "wrong anchor")` | 可理解且不改命题的嘴瓢；否则必须 + self_repair |

`position`：`start` / `before` / `after` / `replace`。`level`：`short` / `medium` / `long`。口语句法：`oral_syntax(topic_fronting|fragment|tail_addition|natural_inversion)`。

## 正例要点

患者回忆病程适合 `filled_pause` + 对时长的 `self_repair`，最终仍回到锁定时长。药名可用可理解 slip 或立刻修正。医生封闭式提问写 `none`。五个以上实质轮应至少让 Plan 里的一处口语结构落到事件上，但不要人人每轮都有。

## 反例

不要缺行。不要把 `none` 和事件写在一起。不要规划咳嗽。不要一行堆三个填充。不要借 restart 引入 Brief 没有的病名。不要用 slip 把一种药改成另一种还不修。不要用失流把「可以」说成「必须」，或把「拉肚子时」削成光杆「手抖」。不要输出 Spoken Base 或最终 JSON。

<!-- STAGE: stage6_surface_generation -->
# Stage 6：Surface Generation

按 Disfluency Plan 将变化应用到 Spoken Base，并只输出既定的最终 JSON。输入不含原始线上对话。

逐条执行：

- 不得省略、合并 Spoken Base 的发言轮。顺序、说话人与底稿一致。丢掉行号和许可证列，只把台词写入 `text`。仅当 `repair_targets` 要求 `split_turn` / `insert_turn` 时才改轮次。
- 最终每轮优先 ≤ 二十汉字，含失流硬上限四十。不得出现 `：` `；`。不用阿拉伯数字（药名/检查名原文除外）。
- 必须完整实现每个计划事件；未计划的部分保持 Spoken Base 的医学含义。
- 最终文本中的所有显式失流都必须来自 Disfluency Plan。碰过锚点的，最终仍须通过该行 C 的四问。
- 仅用 `……` 表示 `silent_pause`。
- 必须落实 Director HABITS 与 Plan PERSONA_TARGETS；至少一处听得见接话方式。
- echo 只复述 2–6 字关键片段，同轮或自己下一轮必须推进。接对方实质内容时应听得出接住了上一轮。
- 同一人连续实质轮最多 2；第 3 条前必须有对方短回应。一轮只保留一条实质。
- 不得点名或索要性别；不得由医生问起年龄。
- 不得把医生建议写成患者既往行为或依从承诺。
- 失流不得削平 `keep`/`when`/`tense`。禁止把发作期/情境问写成平时，把过去写成现在。
- 没有括号动作；不残留线上动作。
- 必须执行人设习惯，可有倒装、词块重复、起句重启、术语检索；口误只要上下文能还原正确医学含义。短回复须随功能变化，不要连续堆「好、嗯好、知道了」。

## 输入

Output identity JSON + Brief + Director + Plan + Spoken Base + Disfluency Plan。修复时另有 `repair_mode`、`previous_dialogue`、`repair_targets`。

## 输出（唯一最终格式）

```json
{"dialogue_id":0,"source":"","meta":{"sex":null,"age":null,"language":"Chinese"},"dialogue":[{"speaker":"患者","text":"string"}]}
```

`meta.sex` 只能为 `男`、`女` 或 `null`；`meta.age` 只能为非负整数或 `null`；`meta.language` 只能为 `Chinese` 或 `null`。`speaker` 只能为 `患者` 或 `医生`。

## 正例要点

底稿「可以查。」+ `restart(start, "这个，呃")` → `这个，呃，可以查。` 力度仍是可以。底稿「夜里口干，查过没有？」必须保住承上。底稿「拉肚子那阵手抖了吗」不得实现成「有手抖吗」。底稿「这阵子药没吃」不得实现成「从来不吃药」。人设「焦点放句尾」可落成「能查吗这个？」；人设「半句 echo」可落成「口干这块啊」。

## 反例

不要输出中间格式或许可证。不要自造计划外的失流。不要写成病历体：「考虑到您的体质存在变化，因此并不需要长期用药。」同一医学含义应是「不一定要吃药」。不要硬塞「你必须吃药，呃不是，也许不用」。不要把「可以」写成「查一下看看」。不要把「偶尔腿抽」写成「腿一直抽」。不要把远距情境削成平时。不要把以前有过写成现在还这样。不要把三条建议焊回一轮。不要医生连说四句无人接。不要患者问能不能查、实现成少熬夜。不要连续三次「好 / 嗯好 / 知道了」。不要括号动作。不要阿拉伯数字。不要残留上传、在线、发图。

<!-- STAGE: stage6_surface_repair -->
# Stage 6：Surface Repair

沿用 Surface Generation 的全部边界。根据 `repair_targets` 做最小、定点修复；保留未被点名的有效轮次。不得因修复而加入任何病例或医学信息，也不得重新设计整段对话。只执行 `scope=surface` 的 targets。

`action` 只能为 `rewrite_turn` / `split_turn` / `merge_turn` / `insert_turn` / `remove_turn` / `move_turn`。

## 输入

identity + 五个中间区块 + `repair_mode` + `previous_dialogue` + `repair_targets`。

## 输出

与 Surface Generation 的最终格式完全相同。

## 正例要点

目标指出「药名内部无动机断裂」→ 把半截药名补全为同一锁定药名，不要顺带加入别的药。目标指出「可以写成必须」→ 改回可以。目标指出「听成平时手抖」→ 补回拉肚子那阵。目标指出「无承上换题」→ 先带已出口短词再推进。目标指出「问句答非所问」→ 先答该问。

## 反例

不要重写整段。不要借修复加剂量、疗程或新解释。不要把结构问题（Brief 漏锁）放在本 stage 硬改。

<!-- STAGE: stage7_clinical_naturalness_judge -->
# Stage 7：Clinical / Naturalness Judge

审查生成对话。优先守住所有临床约束和四问，同时阻止文绉绉、逐句改写、机械短回复、过度表演和不合理线下内容。不要因为顺序变化、措辞变化、医生/患者都有卡壳，或存在正常口语语法而误判。不要问「内容是否大致正确」。

## 输入

identity + Brief + Director + Plan + Spoken Base + Disfluency Plan + 生成对话 JSON。不含原文。

## 输出

```json
{
  "verdict":"pass",
  "checks":[
    {"rule":"constraint_coverage","pass":true,"violations":[]},
    {"rule":"constraint_drift","pass":true,"violations":[]},
    {"rule":"clinical_fidelity_and_modality","pass":true,"violations":[]},
    {"rule":"no_synthetic_case_detail","pass":true,"violations":[]},
    {"rule":"offline_realism","pass":true,"violations":[]},
    {"rule":"persona_realization","pass":true,"violations":[]},
    {"rule":"spoken_naturalness","pass":true,"violations":[]},
    {"rule":"short_turn_rhythm","pass":true,"violations":[]},
    {"rule":"uptake_and_reply","pass":true,"violations":[]},
    {"rule":"short_reply_variation","pass":true,"violations":[]},
    {"rule":"format","pass":true,"violations":[]}
  ],
  "repair_targets":[]
}
```

`verdict` 只能是 `pass`、`repair` 或 `fail`。`pass` 时 `repair_targets` 为 `[]`。`repair` 时 targets 必须非空，且每条对应至少一项失败检查。`fail` 只用于原始输入不足、Brief 无法从原文安全恢复，或已达修复上限；必须给出 `failure_class`（`brief_error` / `plan_coverage` / `unrepairable`）与 `failed_rules`，且 `repair_targets=[]`。

每条 target 至少含 `scope`、`action`、`instruction`。`scope=surface` 时 action 只能为 `rewrite_turn` / `split_turn` / `merge_turn` / `insert_turn` / `remove_turn` / `move_turn`，并给 0-based `turn_index`。`scope=brief` / `director` / `plan` / `spoken_base` 时 action 为 `repair_block`，并列出相关 `constraint_ids`。

## 判定细则

- `constraint_coverage`：所有 `must_surface` 均表达；SETS 每个成员都必须单独说出。药物、治疗、缓解、预防、忌口、生活方式、随访等都在范围内。合并重复可以，漏掉或焊成一条不行。
- `constraint_drift`：对每条 `must_surface` 过四问。列出失败的那一问。`keep`/`when` 隔开后听不见、力度变了、时态变了、多出 C 没说过的事，均失败。远距情境听成平时手抖失败。以前有过听成现在还这样失败。
- `clinical_fidelity_and_modality`：不新增/反转/强化医学信息；患者不替医生下新结论；「可以/考虑/不一定」保留原力度。
- `no_synthetic_case_detail`：不允许新增患者症状、时间、诱因、检查、结果、经历、疗效或回答。
- `offline_realism`：无上传、在线、照片、平台等远程行为；但不得误删本来属于症状发生经过的地点/时间背景。
- `persona_realization`：逐项检查 Plan 的 PERSONA_TARGETS。每个习惯必须在对应角色至少一个具体 turn 可见。
- `spoken_naturalness`：五个以上实质轮若除了「嗯/哦」没有任何自然的倒装、省略、重启、重复、检索、echo、词序变化或口语表达，应修复；整段还必须至少有三处非纯语气词的口语结构。
- `short_turn_rhythm`：一轮只允许一条实质。一轮多条独立约束、SETS 成员焊一条、超过约三十五字且含多个事实组，应拆。同一人连续第 3 条实质无人接失败。优先交替，不为交替空造过渡轮。
- `uptake_and_reply`：对方实质后无承上就换无关主题失败。echo 空转停住失败。患者问句后医生用无关约束当答案失败。`reacts_to` 对不上失败。清单第二条前单独 `嗯` 合格。
- `short_reply_variation`：相邻三次短确认不应机械重复同一「好/嗯好/知道了」。
- `format`：最终 object、speaker、中文 text、中文数字、无动作括号、无单轮超过六十字均正确。

修复目标必须具体、最小化。结构层问题（漏锁 `when`、漏覆盖 C）不要只改表面措辞。

## 正例要点

五个以上实质轮全是完整书面句 → `repair`，`scope=surface`，`rewrite_turn` 改为倒装或省略，不要只加嗯。医生人设是「先 echo」却一处也没有 → 指定一轮加半句 echo。一轮三条建议或医生连说四句无人接 → `scope=plan` 拆轮并插入短回应。患者问能不能查、医生说少熬夜 → `scope=plan` 或 `spoken_base`，先答该问。手抖听成平时 → 若 Plan 把情境拆太远，用 `scope=plan`；若只是该轮措辞丢了拉肚子，用 `scope=spoken_base` 或 `surface`。Brief 漏写 `tense` 或 `SETS` → `scope=brief`。

## 反例

不要因为换了说法就判失败。不要因为有卡壳就判失败。不要写「语义大致正确」然后 `pass`。不要把 Brief 漏锁当成 surface 小改。不要输出空 `repair` 且无 targets。不要把评测样本原句写进 instruction。
