#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Convert cleaned medical dialogues into a more natural offline conversation style
using DeepSeek-V4-Flash (thinking mode).

Input schema (one JSON object per line):
{
  "dialogue_id": 1283,
  "source": "ReMeDi-base",
  "meta": {"sex": "女", "age": 31},
  "dialogue": [
    {"speaker": "患者", "text": "..."},
    {"speaker": "医生", "text": "..."}
  ]
}

Output schema (one JSON object per line, same fields):
{
  "dialogue_id": 1283,
  "source": "ReMeDi-base",
  "meta": {"sex": "女", "age": 31},
  "dialogue": [
    {"speaker": "患者", "text": "..."},
    {"speaker": "医生", "text": "..."}
  ]
}
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List
from tqdm import tqdm
from openai import OpenAI


SYSTEM_PROMPT = """你是一个中文医疗对话"线下门诊重构"助手。

任务：
把输入的结构化医患对话，整体重构成"线下真实门诊"里更自然的口语对话。
不是逐句润色，而是纵观整个对话，重新组织成更像真实面诊的对话，可以改变节奏和表达。
保留医疗事实、说话人身份和医学含义，不要自行补充新的症状、检查、诊断、药名或治疗建议，需要原有的保留药名，治疗建议。

改写要求：
1. 保持原始语义不变，只做表达层面的自然化。
2. 输出要像真人说话：可以加入口头语、停顿、重复、纠正、犹豫词，例如"嗯""啊""这个""就是""呃""对对""稍微"等。
3. 不要把每句话都改得很夸张；整体要像真实门诊，不要像表演。
4. 可以改变发言顺序
5. 不允许同一说话人连续两句。
6. 对于"检查""用药""持续时间""否认/确认"等事实，必须严格保留。
7. 不要新增免责声明、总结、解释，不要输出分析过程。
8. 只输出 JSON，不能输出多余文字。
9. 不能有任何用“（）”表示动作或者注释的文本，只能由说出口的文本组成

线下场景适配（重要）：
- 所有"发照片""发图""上传检查报告""发给我看""发来看看"等线上行为，必须改为线下动作：
  例如："舌苔照片发给我看" → "方便伸一下舌头让我看看舌苔吗"
  例如："把检查结果发来看看" → "检查报告带来了吗，给我看一下"
  例如："先去医院做个踝关节磁共振" → "可以做个踝关节磁共振"
  例如："明天去医院做一下xx检查" → "最好做一下xx检查"
- 所有"在线咨询""平台""回复慢了""久等了""问题关闭"等网络客服套话，直接删除或改为线下打招呼（如"你好，坐吧"）。
- 所有"语音""视频""私信"等线上交互方式，转换为面对面交流的动作或直接删除。
- 任何其他不会存在于线下门诊环境的对话内容，需要你仔细识别并进行转换。

日常对话常见情况适配：
- 患者在专业名词上可能会存在口误嘴飘，记不清药名/检查，比如
  - 左氧氟沙星 → 左痒啥的/左，左氧沙氟星？/左什么什么星
- 不会有特别长的单次发言，将其分割成若干句话以及对方的回应，如("好的好的"，"哦哦"，"嗯")
- 尽量不要单次发言提出超过一个观点/医嘱/症状（特别是长内容），语句连接可以增加("啊", "嗯","呃，还有"等语气连接词)
- 单次发言不要超过40个字。

数字转汉字（重要）：
- 所有数字必须转换成汉字或大概数值描述，不能出现阿拉伯数字。
  例如："10天" → "十天"或"十来天"
  例如："34.6度" → "三十四度六"
  例如："38.5℃" → "三十八度五"
  例如："150cm，122斤" → "一米五，一百二十二斤"
  例如："一次4片，一天3次" → "一次四片，一天三次"
  例如："3-5g" → "三到五克"

超长文本分割（重要）：
- 当患者或医生单次发言过长（如罗列一大堆症状、或长篇大论的医嘱），必须拆分为多轮对话，
  让对方有回应（如"嗯""然后呢""这倒没有"），以符合真实面对面交流的节奏。

输出格式：
{
  "dialogue_id": <原值>,
  "source": <原值>,
  "meta": {
    "sex": <原值>,
    "age": <原值>
  },
  "dialogue": [
    {"speaker": "患者", "text": "..."},
    {"speaker": "医生", "text": "..."}
  ]
}

注意：
- speaker 只允许使用"患者""医生"（若输入里有其他说话人，则原样保留）。
- 不要输出 markdown。
- 不要输出代码块。
- 不要输出额外字段。

如下是常见的真实门诊对话语音转录实例，你需要转换成JSON格式的对话，内容类似如下的对话：

## sample_001

| 说话人 | 内容 |
|---|---|
| 旁白/录音 | 可以，我读医生。 |
| 医生 | 病人王某，女，三十二岁。你好，我是陈医生，你的主管医生。现在需要详细了解你的病情，请配合回答。 |
| 患者 | 好的，陈医生。 |
| 医生 | 这次来医院主要哪里不舒服？ |
| 患者 | 这几天小便的时候呢，特别痛，还有尿频尿急，今天开始腰也酸的厉害。 |
| 医生 | 症状出现多久了？有没有发热？ |
| 患者 | 尿痛有四天了，昨晚开始有低烧，呃，自己量过体温，三十七度八左右吧，早上又烧到了三十八度五。 |
| 医生 | 小便颜色正常吗？有没有血尿或浑浊？ |
| 患者 | 颜色呢是比较深，有点浑浊，今早看到尿里有点血丝。 |
| 医生 | 治疗过吗？ |
| 患者 | 啊，没有治疗，发现问题我就直接来医院了。 |
| 医生 | 之前出现过类似症状吗？比如尿路感染或肾盂肾炎？ |
| 患者 | 去年得过一次尿路感染，吃了抗生素好了，但这次更严重。 |
| 医生 | 平时喝水多吗？熬夜或久坐吗？ |
| 患者 | 工作忙，喝水比较少，每天坐办公室超过八小时。 |
| 医生 | 你有其他慢性病吗？比如高血压、糖尿病？ |
| 患者 | 没有。 |
| 医生 | 有肝炎、结核等传染病吗？ |
| 患者 | 没有。 |
| 医生 | 有没有药物过敏？ |
| 患者 | 呃，青霉素过敏。 |
| 医生 | 月经规律吗？多少岁来的月经？末次月经什么时候？经量如何？ |
| 患者 | 十三岁开始来月经，月经基本正常，末次是两周前，量中等，没有明显痛经。 |
| 医生 | 结婚了吗？生育过吗？ |
| 患者 | 结婚了，有一个女儿，三岁顺产的。 |
| 医生 | 父母身体健康吗？家人有没有反复尿路感染或肾脏病史？ |
| 患者 | 父母身体还好，母亲有肾结石，父亲有高血压。 |
| 医生 | 现在测个体温，三十八点二摄氏度，血压一百二十 七十五毫米汞柱。我给你检查下腹部和腰部。查体后，左肾区叩击痛阳性，下腹部耻骨上压痛阳性，无反跳痛。尿道口稍红肿，无异常分泌物。门诊尿常规显示白细胞三三个加，亚硝酸盐阳性，血常规白细胞十二乘以十的九次方每升，已经做了尿培养，结果明天出，等下安排泌尿系超声，排除其他疾病。 |
| 患者 | 谢谢医生。 |
| 医生 | 根据目前检查，考虑急性肾盂肾炎，需要住院静脉用抗生素。 |
| 患者 | 明白了，我会配合治疗。 |
| 医生 | 护士会来抽血做肝肾功检查，抗生素先用头孢类，避开过敏药物，有情况随时沟通。 |
| 患者 | 好的，辛苦你了。 |

## sample_002

| 说话人 | 内容 |
|---|---|
| 医生 | 你好，乐先生对吧？我来问一下你的情况哈，我是刘刘医生，你怎么不舒服啊？ |
| 患者 | 头晕？ |
| 医生 | 哦，有多久了？ |
| 患者 | 有一两个月了吧，两个月之前就有。 |
| 医生 | 当时是什么样的？怎么样的情况啊？方便讲一下吧。 |
| 患者 | 当时是我正在上班，上班的时候突然就一起来，一 起来之后就晕了。 |
| 医生 | 嗯，是昏昏沉沉还是天旋地转啊？ |
| 患者 | 昏昏沉沉。 |
| 医生 | 昏昏沉沉的是吧？ |
| 患者 | 啊，嗯。 |
| 医生 | 当时除了说有头晕，还有别的不舒服吗？ |
| 患者 | 没有。 |
| 医生 | 哦，恶心呕吐啊这些？ |
| 患者 | 没有。 |
| 医生 | 心慌胸闷胸痛有没有啊？ |
| 患者 | 没有。 |
| 医生 | 哦，当时还有耳鸣呢，这些有吗？ |
| 患者 | 耳鸣有一点。 |
| 医生 | 啊，耳鸣是什么样的性状啊？ |
| 患者 | 耳鸣是好像有点响。 |
| 医生 | 哦，像那种蝉蝉鸣还是说像那种电流声呢？ |
| 患者 | 好像，是那个敲敲敲东西那种响声。 |
| 医生 | 哦，敲东西的声音是吧？ |
| 患者 | 嗯。 |
| 医生 | 除了这还有别有没有听力下降啊？ |
| 患者 | 没有。 |
| 医生 | 头痛有没有啊？ |
| 患者 | 没有。 |
| 医生 | 没有是吧？当时有没有看呢？ |
| 患者 | 当时没看。 |
| 医生 | 没没看，然后怎么样就好了呢？ |
| 患者 | 休息休息，一下午加一晚上，我请假休息后第二天就好了。 |
| 医生 | 休息后就好了是吧？ |
| 患者 | 嗯。 |
| 医生 | 行。呃，最近有再发发吗？ |
| 患者 | 最近就就这段时间，有有个把星期吧。 |
| 医生 | 啊，嗯，个把星期前是什么情况？当时在干嘛？ |
| 患者 | 当时在上班嘛，上班上班就晕。 |
| 医生 | 嗯。 |
| 患者 | 晕了这段时间比较持续的比较长，一直都在晕。 |
| 医生 | 哦，持续时间比较长是吧？是发作就是每天都发还是说一直一直都是晕？ |
| 患者 | 呃，除了睡觉睡着了就好像没有这种感觉了，要不睡觉的话，就是一直都是晕。 |
| 医生 | 一直都是晕是吧？ |
| 患者 | 这是间歇性的。间歇性的。 |
| 医生 | 嗯，每次大概大概多久？ |
| 患者 | 大概有时候十几分钟吧，有时候几分钟。 |
| 医生 | 哦，一天发几次啊？ |
| 患者 | 啊，估计至少好多次哦。 |
| 重叠 | [重叠: 哦，症状 / 我没记他] |
| 医生 | 哦，症状跟之前差不多吗？ |
| 患者 | 症状跟之前差不多。 |
| 医生 | 啊，行，就是耳鸣呢？ |
| 患者 | 耳鸣也耳鸣，还有点耳鸣。 |
| 医生 | 就跟之前比呢？ |
| 患者 | 比原来那一次的耳鸣好一点点。 |
| 医生 | 哦，有好一点是吧？ |
| 患者 | 嗯，没那么厉害。 |
| 医生 | 当时有去看吗？ |
| 患者 | 就是在四号，这个月四号我就看了，就是在前几天我就看了。 |
| 医生 | 啊，去社康看了是吧？ |
| 患者 | 抽血化验了。 |
| 医生 | 啊，抽血化验了，但是没没拿到结果哈。 |
| 患者 | 结果这个没达到没达到效果，啊，就是还是晕有。 |
| 医生 | 哦，当时有测血压是吧？ |
| 患者 | 测血压，测过。 |
| 医生 | 啊，最高有多高？ |
| 患者 | 最高一百六十多。 |
| 医生 | 嗯。低压呢？ |
| 患者 | 低压一百一十多。 |
| 医生 | 一百一十多是吧？行。就是头晕，休息后会稍微好一点，还是说没有改善？ |
| 患者 | 好像休息后没什么大改善吧，还好好一点点。 |
| 医生 | 哦|
| 患者 | 就没那么频繁，就没那么晕的频繁。 |
| 患者 | 嗯。 |
| 医生 | 当时社康有有给你开药开药吗？ |
| 患者 | 降压药。 |
| 医生 | 啊，开了。什么疏通血管的药就是。开了啥药？ |
| 患者 | 我我不知道名字我忘记了，反正降压药吧。 |
| 医生 | 我说我说开了厄贝沙坦和那个氨氯地平，哈。我看了下，嗯，一天吃一次对吧？ |
| 患者 | 一天一次一次一片。 |
| 医生 | 一次一颗。吃了之后血压控制的还行是吧？ |
| 患者 | 好像好一点。 |
| 医生 | 好一点是吧？血压有多高？平？就是。 |
| 患者 | 血压接近正常了，高压一百三十九。 |
| 医生 | 嗯。低压的话还还高一点点，还有还有九十六，九十六。但是症状,头晕啊这些有改善没有？ |
| 患者 | 改善没有改善是吧？头晕没改善。 |
| 医生 | 哦，这次来就想看一下头晕究竟是什么情况，对不对？ |
| 患者 | 是是，我为什么这个降血压不高，还晕呢我就想问问。 |
| 医生 | 好，最近睡眠怎么样？ |
| 患者 | 睡眠不是很好。 |
| 医生 | 睡眠不好是吧？啊，胃口呢？ |
| 患者 | 胃口一般。 |
| 医生 | 胃口一般是吧？ |
| 医生 | 嗯。 |
| 医生 | 精神状态还可以是吧？ |
| 患者 | 精神状态也不是很好。 |
| 医生 | 啊。 |
| 患者 | 有时候睡觉睡不好。 |
| 医生 | 嗯。 |

## sample_005

| 说话人 | 内容 |
|---|---|
| 医生 | 嗯，可以开始吗？ |
| 患者 | 可以 |
| 医生 | 哎，你好，你是叫李健是吧？ |
| 患者 | 对。 |
| 医生 | 啊，我想问一下，你一开始是怎么不舒服过来的？ |
| 患者 | 就一开始我就是感觉在上班的时候胀痛胀痛的，然后一直冒冷汗，我就就过来了。 |
| 医生 | 左边还是右边？ |
| 患者 | 左边。 |
| 医生 | 左边冒就冒冷汗，这是你第一次痛吗？ |
| 患者 | 嗯，以前有过，以前有过，但是到到输到那个输尿输尿管里面就，我去我去检查，他说可以排出来，就喝吃点药排出来了。 |
| 医生 | 哦，你以前也得过结石也排出来过是吧？ |
| 患者 | 对。 |
| 医生 | 那是多久前的事情了？ |
| 患者 | 五六年了吧。 |
| 医生 | 五六年，这在哪个医院看的还 记得不？ |
| 患者 | 在我们那边，临桂，临桂。 |
| 医生 | 当时就吃了药，然后也没做什么体外碎石，没做什么镜子什么的。 |
| 患者 | 因为那时候只有五毫米。 |
| 医生 | 五毫米，就是吃药就排出来了。 |
| 患者 | 对。 |
| 医生 | 好，好，这一次的话呢，是什么时候开始痛的呢？ |
| 患者 | 就昨晚上我上班，上班的时候就是十一二点。 |
| 医生 | 昨天晚上十一二点，到现在大概也就十一个小时左右了。 |
| 患者 | 对。 |
| 医生 | 好吧。啊，痛的时候是感觉钝钝的痛，还是很尖锐的痛呢？ |
| 患者 | 就胀胀胀痛。 |
| 医生 | 没有很刀割一样的感觉？ |
| 患者 | 没有。 |
| 患者 | 就是他感觉里面就像排不出东西一样，卡在那里。 |
| 医生 | 嗯嗯。咳，然后那个有没有恶心呕吐啊？ |
| 患者 | 胃口不好算不算？ |
| 医生 | 胃口不好是痛了之后才开始出现的。 |
| 患者 | 对。 |
| 医生 | 还是以前都有。 |
| 患者 | 没有胃就痛的时候就就吃不中，晚上吃饭吃不了。 |
| 医生 | 啊，痛了之后开始吃东西也不好了，感觉，但是没有吐是吧？ |
| 患者 | 没有吐。 |
| 医生 | 头晕头痛这些有没有啊？ |
| 患者 | 嗯，刚上完夜班，现在也有点。 |
| 医生 | 觉得是熬夜的时候有点晕是吧？ |
| 患者 | 对。 |
| 医生 | 小便呢？小便情况怎么样？ |
| 患者 | 小便正常。 |
| 医生 | 小便是正常，颜色也没有变化。 |
| 患者 | 嗯，尿黄。 |
| 医生 | 尿黄。大便怎么样啊？ |
| 患者 | 大便是有点拉不出来的感觉。 |
| 医生 | 大便有点想拉拉不出来的感觉。 |
| 患者 | 因为可能是没吃东西还是怎么样。 |
| 医生 | 哦，那是你昨天晚上开始痛的时候有没有上过厕所？ |
| 患者 | 上啊。 |
| 医生 | 也上过，也就是正常的排出来是吧？ |
| 患者 | 对。 |
| 医生 | 大便有没有成型啊？ |
| 患者 | 啊，不成型。 |
| 医生 | 不成型，行行。有没有什么其他的慢性疾病之类的？ |
| 患者 | 没有。 |
| 医生 | 没有？有没有做过别的什么手术？ |
| 患者 | 哎，慢性疾病乙肝算吗？ |
| 医生 | 乙肝也算吧，也算，是是这个乙肝小三阳还是大三阳？ |
| 患者 | 大三阳。 |
| 医生 | 大三阳。 |
| 患者 | 但是但是已经那个转氨酶已经已经降已经降到正常值了。 |
| 医生 | 肝酶转氨酶都是正常的，是吧？ |
| 患者 | 啊，对。 |
| 医生 | 啊，之前有没有吃过药？ |
| 患者 | 之前就是吃吃药吧，吃药吃好了，他们他们我去复检的时候他们说可以了。 |
| 医生 | 当时是吃了抗病毒药之类的，但是不是很清楚是吧？ |
| 患者 | 对，因为他我要我我去复，他让我去复检，然后我就去了。 |
| 患者 | 啊，就是说，呃，已经已经正常了。 |
| 医生 | 行，这个没问题。那还没有别的再吃药的慢性疾病之类的？ |
| 患者 | 没有。 |
| 医生 | 高血压糖尿病都没有哈。 |
| 患者 | 没有。 |
| 医生 | 有没有做什么手术之类的？ |
| 患者 | 啊，做过皮脂。 |
| 医生 | 皮皮脂。 |
| 患者 | 就那个什么。 |
| 医生 | 皮脂腺囊肿。 |
| 患者 | 对。 |
| 医生 | 啊，皮脂，哪个部位的？ |
| 患者 | 就后背。 |
| 医生 | 后背的切了，后来就好了是吧？ |
| 患者 | 对。 |
| 医生 | 啊，但是做手术什么的，过程都顺利吧？ |
| 患者 | 顺利。 |
| 医生 | 没有对麻药过敏什么的啊？ |
| 患者 | 没有。 |
| 医生 | 自己也没有发现现什么过敏的。 |
| 患者 | 没有。 |
| 医生 | 都没有是吧？ |
| 患者 | 因为从小的话，我们小时候生病都打青霉素的。 |
| 医生 | 啊，都没有问题哈。结婚了没有？ |
| 患者 | 没有。 |
| 医生 | 还没结婚是吧？ |
| 患者 | 对。 |
| 医生 | 行，家里面有没有什么遗传病史之类的呀？爸妈有没有高血压糖尿病？ |
| 患者 | 没有。 |
| 医生 | 肿瘤病史有没有？ |
| 患者 | 没有。 |
| 医生 | 都没有哈。行行，好，你基本情况我们都清楚了，好吧？ 好，好。 |
| 医生 | 有需要补充不？ |
| 患者 | 没有。 |
| 医生 | 行行，感谢你的配合哈。行，因为呢，呃，再跟你补充讲一下，我是你的主管医生陈医生。啊，这个可以关了吧？ |
| 患者 | 可以了。 |
| 医生 | 然后呢，你的片子我也看了，你的病史我也比较明确了。你的那个片子看到呢，就是左侧输尿管上段有一个比较大的一个结石，啊，已经横径都有一点多公分了。这种结石呢，他自己排肯定是排不出来了的，这种结石。 |
"""

FEW_SHOT = [
    # Example 1: online behavior → offline action + number → Chinese
    {
        "role": "user",
        "content": json.dumps(
            {
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
                    {"speaker": "医生", "text": "嗯。可以中药治疗。"},
                ],
            },
            ensure_ascii=False,
        ),
    },
    {
        "role": "assistant",
        "content": json.dumps(
            {
                "dialogue_id": 1283,
                "source": "demo",
                "meta": {"sex": "女", "age": 31},
                "dialogue": [
                    {"speaker": "患者", "text": "医生你好，我想问一下，我这种气虚、阴虚、血瘀、湿热的体质，该怎么调理啊？"},
                    {"speaker": "医生", "text": "嗯，坐吧。您这个情况啊，有点气阴两虚、痰湿体质。呃，可以喝，吃中成药，也可以自己熬点中药。"},
                    {"speaker": "患者", "text": "哦这样。"},
                    {"speaker": "医生", "text": "对，现在主要有哪些不舒服？"},
                    {"speaker": "患者", "text": "就是经常头晕，四肢有点，没什么力气，还容易心慌。"},
                    {"speaker": "医生", "text": "平时肝火大不大？脾气怎么样？"},
                    {"speaker": "患者", "text": "呃，脂肪肝，不过脾气还行。"},
                    {"speaker": "医生", "text": "身高体重是多少？"},
                    {"speaker": "患者", "text": "一米五，一百二十二斤。"},
                    {"speaker": "医生", "text": "嗯，稍微有点偏胖。"},
                    {"speaker": "患者", "text": "嗯对。"},
                    {"speaker": "医生", "text": "你这个心脏，唔，供血可能不太好。来，方便伸一下舌头让我看看舌苔吗？"},
                    {"speaker": "患者", "text": "啊，好的。"},
                    {"speaker": "医生", "text": "嗯...看了一下，可以开点中药调理一下。"},
                ],
            },
            ensure_ascii=False,
        ),
    },
    # Example 2: long text splitting
    {
        "role": "user",
        "content": json.dumps(
            {
                "dialogue_id": 1473,
                "source": "demo",
                "meta": {"sex": "女", "age": 33},
                "dialogue": [
                    {"speaker": "患者", "text": "肚脐眼周围疼痛并伴有消化不良"},
                    {"speaker": "医生", "text": "你好，这种情况多长时间了？"},
                    {
                        "speaker": "患者",
                        "text": "一直肠胃不好，前一阵子胃疼，做了胃镜，轻微胃炎，大夫建议中药调理，吃了一个月中药后没啥效果，发现自己肚脐眼里面四周疼，肠道疼，又看了西医，开了庆大霉素，胶体果胶铋，枫蓼肠胃康，还有一个专治肠炎的忘记叫啥名字了，吃了近半个月强了很多，现在主要是肚脐周围隐痛，不像之前那么明显的痛了。饮食也很注意，但是每次吃完饭后都感觉不消化，屁多，吃馒头面条之类的也不消化。吃完饭后感觉胃里有石头一样，伴有特别轻微的恶心但是吐不出",
                    },
                    {"speaker": "医生", "text": "大便正常吗？反酸，烧心，胃胀的症状有吗？"},
                ],
            },
            ensure_ascii=False,
        ),
    },
    {
        "role": "assistant",
        "content": json.dumps(
            {
                "dialogue_id": 1473,
                "source": "demo",
                "meta": {"sex": "女", "age": 33},
                "dialogue": [
                    {"speaker": "患者", "text": "大夫，我最近肚脐眼周围老是疼，而且吃东西也不怎么消化。"},
                    {"speaker": "医生", "text": "嗯，这种情况有多长时间了？"},
                    {"speaker": "患者", "text": "我一直肠胃就不太好。前一阵子胃疼，去做了个胃镜，说是轻微胃炎。"},
                    {"speaker": "医生", "text": "当时有开药吗？"},
                    {"speaker": "患者", "text": "当时大夫建议中药调理，但我吃了一个月中药，感觉也没啥效果。后来就发现肚脐眼四周开始疼，感觉像是肠子疼。"},
                    {"speaker": "医生", "text": "嗯，然后呢？"},
                    {"speaker": "患者", "text": "后来又去看了西医，给我开了庆大霉素、胶体果胶比，还有枫，我想想，一个枫字开头的药，好像还有一个治肠炎的药，也忘了。"},
                    {"speaker": "医生", "text": "这样啊。吃了这些药感觉怎么样？"},
                    {"speaker": "患者", "text": "吃了快，呃，半个月吧，确实好多了。现在主要是肚脐，周围隐隐痛，没之前那么疼了。"},
                    {"speaker": "医生", "text": "消化怎么样？"},
                    {"speaker": "患者", "text": "饮食我很，已经注意了，但每次吃饭，呃，吃完还是觉得不消化，老放屁。"},
                    {"speaker": "医生", "text": "哦。"},
                    {"speaker": "患者", "text": "呃，比如吃馒头啊，面条这种也觉得堵得慌。吃完饭胃里就像一块，有块石头一样。"},
                    {"speaker": "医生", "text": "嗯。还有吗？"},
                    {"speaker": "患者", "text": "嗯...有点轻微的恶心，但吐不出来。"},
                    {"speaker": "医生", "text": "哦好的。那大便正常吗？有没有反酸、烧心、或者胃胀的感觉？"},
                ],
            },
            ensure_ascii=False,
        ),
    },
    {
        "role": "user",
        "content": json.dumps(
            {"dialogue_id": 133, "source": "ReMeDi-base", "meta": {"sex": "男", "age": 27}, "dialogue": [{"speaker": "患者", "text": "坐久了头晕。头疼杂回事有颈椎病"}, {"speaker": "医生", "text": "你平时生活作息规律吗？"}, {"speaker": "患者", "text": "晚上12到2点睡觉，早上8点起床。坐久了 起来就是头晕 我有颈椎病"}, {"speaker": "医生", "text": "你平时有体育运动锻炼吗？"}, {"speaker": "患者", "text": "没有 基本很少。啥问题啊我这个"}, {"speaker": "医生", "text": "一般头晕能持续多长时间？有没有天旋地转或站立不稳的情况。马上坐下或者躺下，能不能缓解？"}, {"speaker": "患者", "text": "一小会。能站立 就是往边上靠 一会就好了。没有坐下 也能缓解。几秒内"}, {"speaker": "医生", "text": "缺乏运动，引起的血压一过性偏低"}, {"speaker": "患者", "text": "我血压一直平稳。不是颈椎病吗"}, {"speaker": "医生", "text": "这种情况不是颈椎病的问题，就是突然站起来瞬间血压不能及时升高"}, {"speaker": "患者", "text": "不是的。是我上班坐这里 突然晕一下。然后出门就头晕。问题大吗"}, {"speaker": "医生", "text": "你平时熬夜吗？。长时间做的话，有可能会出现头晕的情况，但是这个头晕主要与睡眠不足熬夜和过于紧张有关系。这种情况可以出现短时间的头晕。长时间坐"}, {"speaker": "患者", "text": "熬夜 精神一直紧张。坐的屁股疼"}, {"speaker": "医生", "text": "那你这种原因就是与熬夜直接相关。会出现短时间的大脑功能紊乱"}, {"speaker": "患者", "text": "我最近都凌晨一点左右到3点睡觉 精神极度紧张"}, {"speaker": "医生", "text": "你这种情况避免熬夜适量运动锻炼，保持轻松的心情，就会好"}, {"speaker": "患者", "text": "严重吗。经常也晕"}, {"speaker": "医生", "text": "这种情况本身不严重，是你生活作息规律不好引起的。参考总结，看还有什么疑问"}, {"speaker": "患者", "text": "严重不"}, {"speaker": "医生", "text": "不严重，调整好作息规律就可以"}]}, ensure_ascii=False
        )
    },
    {
        "role": "assistant",
        "content": json.dumps({
            "dialogue_id": 133,
            "source": "ReMeDi-base",
            "meta": {"sex": "男", "age": 27},
            "dialogue": [
                {"speaker": "患者", "text": "医生，我坐久了就头晕，还头疼。我有颈椎病，您说这是咋回事？"},
                {"speaker": "医生", "text": "嗯，先别急。你平时睡眠怎么样，作息规律吗？"},
                {"speaker": "患者", "text": "不太规律，晚上十二点到半夜两点才睡，早上八点起。"},
                {"speaker": "医生", "text": "平时有运动吗？"},
                {"speaker": "患者", "text": "基本没有，很少动。"},
                {"speaker": "医生", "text": "这个头晕，一般能持续多长时间？"},
                {"speaker": "患者", "text": "就一小会儿，几秒钟吧。"},
                {"speaker": "医生", "text": "有没有天旋地转、或者站不住的感觉？"},
                {"speaker": "患者", "text": "能站住，就是得往边上靠一下，一会儿就好了。"},
                {"speaker": "医生", "text": "坐下来能缓解吗？"},
                {"speaker": "患者", "text": "坐下也能好点。医生，我这到底啥问题啊？"},
                {"speaker": "医生", "text": "我觉得你这个，可能是缺乏运动，导致血压一过性偏低。"},
                {"speaker": "患者", "text": "啊？我血压一直正常啊，会不会是呃，颈椎病引起的吗？"},
                {"speaker": "医生", "text": "不太像颈椎病的问题。更像是突然站起来的时候，血压没能及时升上去。"},
                {"speaker": "患者", "text": "唔，可我有时候是坐着就晕，出门也晕。问题大不大啊？"},
                {"speaker": "医生", "text": "哦？那你熬夜严不严重？"},
                {"speaker": "患者", "text": "也不，挺严重的，最近基本凌晨一点到两，三点才睡，精神也挺很紧张。"},
                {"speaker": "医生", "text": "嗯，那就是熬夜加上精神紧张导致的，大脑功能短时间有点点紊乱。"},
                {"speaker": "患者", "text": "严重不？我经常晕。"},
                {"speaker": "医生", "text": "本身不严重，就是作息不好引起的，不严重。"},
                {"speaker": "患者", "text": "哦哦那就好。"},
                {"speaker": "医生", "text": "避免熬夜，适当运动，心情放松一点，慢慢就好了。"},
                {"speaker": "患者", "text": "好的好的知道了，谢谢医生。"}
            ]
        }, ensure_ascii=False),
    },
    {
        "role": "user",
        "content": json.dumps(
			{"dialogue_id": 1494, "source": "ReMeDi-base", "meta": {"sex": "男", "age": 42}, "dialogue": [{"speaker": "患者", "text": "喉咙痒咳嗽，一个月左右"}, {"speaker": "医生", "text": "您好，很高兴为您服务。请问有没有晨起睡前咳嗽啊。平时有没有过敏性鼻炎"}, {"speaker": "患者", "text": "没有鼻炎。一个月前感冒咳嗽，一直到现在"}, {"speaker": "医生", "text": "咳嗽前有没有感冒啊。做了哪些检查。吃了什么药物啊"}, {"speaker": "患者", "text": "感冒了"}, {"speaker": "医生", "text": "有没有抽血查个肺炎支原体抗体和胸片啊"}, {"speaker": "患者", "text": "咽炎，肺炎，支气管炎。血项没问题"}, {"speaker": "医生", "text": "把检查结果发来看看"}, {"speaker": "患者", "text": "现在呼吸时喉咙痒咳嗽。没在身边"}, {"speaker": "医生", "text": "有诊断肺炎吗。输液还是吃药了"}, {"speaker": "患者", "text": "没有。开了点咽炎，肺炎，支气管炎的药"}, {"speaker": "医生", "text": "吃了多久啊。平时有没有药物过敏啊"}, {"speaker": "患者", "text": "没有药物过敏。吃了半个月"}, {"speaker": "医生", "text": "最近吃的药名是什么啊。还记得吗"}, {"speaker": "患者", "text": "阿莫斯林"}, {"speaker": "医生", "text": "阿莫西林。还有呢。目前咳嗽有黄痰吗"}, {"speaker": "患者", "text": "还要三个记不得了"}, {"speaker": "医生", "text": "咳嗽什么时段厉害啊"}, {"speaker": "患者", "text": "这几天没什么痰了，有时是白痰。间接性咳嗽，喉咙一痒，就要咳嗽。人呢。怎么没有回复了"}, {"speaker": "医生", "text": "稍等一下。开车中。可以考虑吃点美敏伪麻溶液和苏黄止咳胶囊看看。如果有黄痰，可以吃点阿奇霉素。感觉有可能是感冒后气道高敏状态。吃点苏黄止咳胶囊和美敏伪麻溶液应该能缓解。如果有效估计三五天就会看到明显效果。咳嗽久了，阿莫西林不建议吃，万一有支原体感染，阿莫西林就无效。避免辛辣食物，避免烟酒刺激。避免再次受凉"}]}, ensure_ascii=False)
    },
    {
        "role": "assistant",
        "content": json.dumps(
			{
            "dialogue_id": 1494,
            "source": "ReMeDi-base",
            "meta": {"sex": "男", "age": 42},
            "dialogue": [
                {"speaker": "患者", "text": "医生，我喉咙痒、咳嗽，差不多一个月了。"},
                {"speaker": "医生", "text": "嗯，早上起来或者睡前咳得厉害吗？有没有过敏性鼻炎？"},
                {"speaker": "患者", "text": "没有鼻炎。就是一个月前感冒了，然后一直咳到现在。"},
                {"speaker": "医生", "text": "感冒后开始的啊。做过哪些检查？"},
                {"speaker": "患者", "text": "血项查过，没问题。后来还查了，说是啥的，咽炎、支气管炎。"},
                {"speaker": "医生", "text": "报告带来了吗？"},
                {"speaker": "患者", "text": "没带身边。现在就是一呼吸喉咙就痒，一呼吸就痒，忍不住想咳。"},
                {"speaker": "医生", "text": "之前吃过什么药吗？"},
                {"speaker": "患者", "text": "吃了半个月，有阿西莫林，还有几个药名字记不住了。"},
                {"speaker": "医生", "text": "哦，阿莫西林，那有没有药物过敏？"},
                {"speaker": "患者", "text": "呃，没有。"},
                {"speaker": "医生", "text": "哦好的，行。现在有黄痰吗？"},
                {"speaker": "患者", "text": "这几天没什么痰了，偶尔有点白痰。就是喉咙一痒就咳，不定时的。"},
                {"speaker": "医生", "text": "咳嗽什么时候比较厉害？"},
                {"speaker": "患者", "text": "好像，好像不定时？痒就咳。医生，这到底怎么回事？"},
                {"speaker": "医生", "text": "我考虑是感冒后气道高敏状态，就是气道还没完全恢复，比较敏感。"},
                {"speaker": "患者", "text": "那怎么治啊？"},
                {"speaker": "医生", "text": "给你开两个药，苏黄止咳胶囊和美敏伪麻溶液，先吃三到五天看看效果。"},
                {"speaker": "患者", "text": "好的。那阿莫西林还要继续吃吗？"},
                {"speaker": "医生", "text": "阿莫西林可以，先停了吧。万一是支原体感染，阿莫西林没什么用。"},
                {"speaker": "患者", "text": "哦行。"},
                {"speaker": "医生", "text": "对，要是后面出现黄痰，再加阿奇霉素。"},
                {"speaker": "患者", "text": "明白了。"},
                {"speaker": "医生", "text": "平时注意一下，辛辣的别吃了，烟酒少碰，别着凉。"},
                {"speaker": "患者", "text": "好，谢谢医生。"}
            ]
        }, ensure_ascii=False)
    }
]


def build_messages(record: Dict[str, Any]) -> List[Dict[str, str]]:
    user_payload = json.dumps(record, ensure_ascii=False)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(FEW_SHOT)
    messages.append({"role": "user", "content": user_payload})
    return messages


def extract_json_object(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    # Fast path.
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # Fallback: extract the first JSON object.
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("No JSON object found in model output")
    obj = json.loads(m.group(0))
    if not isinstance(obj, dict):
        raise ValueError("Model output is not a JSON object")
    return obj


def normalize_output(obj: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "dialogue_id": obj.get("dialogue_id", fallback.get("dialogue_id")),
        "source": obj.get("source", fallback.get("source", "")),
        "meta": obj.get("meta", fallback.get("meta", {})),
        "dialogue": obj.get("dialogue", fallback.get("dialogue", [])),
    }

    # Light validation/cleanup.
    cleaned_dialogue = []
    for turn in out["dialogue"] if isinstance(out["dialogue"], list) else []:
        if not isinstance(turn, dict):
            continue
        speaker = str(turn.get("speaker", "")).strip()
        text = str(turn.get("text", "")).strip()
        if speaker and text:
            cleaned_dialogue.append({"speaker": speaker, "text": text})
    out["dialogue"] = cleaned_dialogue
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert cleaned medical dialogues with DeepSeek-V4-Flash.")
    parser.add_argument("--input", required=True, help="Path to scripts-clean.jsonl")
    parser.add_argument("--output", required=True, help="Path to script-convert.jsonl")
    parser.add_argument("--model", default="deepseek-v4-pro", help="DeepSeek model name")
    parser.add_argument("--base-url", default="https://api.deepseek.com", help="DeepSeek base URL")
    parser.add_argument("--api-key", default=os.getenv("DEEPSEEK_API_KEY", ""), help="DeepSeek API key")
    parser.add_argument("--thinking", action="store_true", help="Enable thinking mode (default recommended).")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--temperature", type=float, default=0.4)
    args = parser.parse_args()

    if not args.api_key:
        raise RuntimeError("Missing API key. Set DEEPSEEK_API_KEY or pass --api-key.")

    client = OpenAI(api_key=args.api_key, base_url=args.base_url)

    in_path = Path(args.input)
    out_path = Path(args.output)

    kept = 0
    failed = 0

    with in_path.open("r", encoding="utf-8") as fin, out_path.open("w", encoding="utf-8") as fout:
        for lineno, line in tqdm(enumerate(fin, 1)):
            line = line.strip()
            if not line:
                continue

            record = json.loads(line)
            if not isinstance(record, dict):
                failed += 1
                continue

            messages = build_messages(record)

            # DeepSeek official docs support OpenAI-compatible chat completions,
            # and JSON output via response_format={"type":"json_object"}.
            # Thinking mode is enabled on the API side; for compatibility we also pass reasoning_effort.
            kwargs = dict(
                model=args.model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=args.temperature,
                max_tokens=args.max_tokens,
            )
            if args.thinking:
                # Official docs expose reasoning_effort for thought effort control.
                kwargs["reasoning_effort"] = "high"

            try:
                resp = client.chat.completions.create(**kwargs)
                content = resp.choices[0].message.content or ""
                obj = extract_json_object(content)
                normalized = normalize_output(obj, record)
                fout.write(json.dumps(normalized, ensure_ascii=False) + "\n")
                kept += 1
            except Exception as e:
                failed += 1
                print(f"[WARN] line {lineno} failed: {e}")
                # Optional fallback: keep the original record if conversion fails.
                # fout.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"Done. kept={kept}, failed={failed}, output={out_path}")


if __name__ == "__main__":
    main()
