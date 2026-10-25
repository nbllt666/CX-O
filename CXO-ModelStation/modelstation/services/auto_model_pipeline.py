"""
一键成模编排服务（提示词/参考音频 → 自动全流程 → 模型文件）

change-id: add-one-click-voice-model-pipeline（spec「一键成模」Task 2/3）。

设计约束：
- 单后台任务串行五阶段：reference → corpus → preprocess → training → collect；
  每阶段独立 try/except，失败置 failed 并带 error，不向调用方抛出。
- 运行注册表为进程内 dict（单 worker 部署语义，与 api/sovits_svc.py 的模块级
  状态约束一致）；同一时间仅允许一个运行（running 存在 → 提交 409 语义）。
- 全程复用既有服务，不新增合成/训练逻辑：
  * reference/corpus：提示词模式走 DatasetBuilderService.submit_pipeline
    （qwen3 初始参考音频 → cosyvoice 批量克隆 → dataset_registry 编号 DS-xxx）；
    上传模式走 register_dataset 编号 + submit(engine=cosyvoice3_zero,
    engine_params={"ref_audio_path": 上传路径})；
  * preprocess：sovits=SoVITSSVCTrainer.preprocess（必须与训练用同一单例，
    满足 start_training 的 _preprocessed 前置检查）；melotts=prepare_filelists；
  * training：sovits 按 api/sovits_svc.py 的模式消费 training_mutex
    （try_begin_training / update_training_task / end_training，终态幂等释放）；
    melotts 互斥由 trainer 内部消费（TrainingInProgressError → run failed，
    error 注明 409 训练冲突语义）；
  * collect：定位 data/models/<类型>/<名>/ 产物；判停（stopped）路径 trainer
    不收集产物时，此处调用 trainer._collect_outputs 兜底（容忍仅剩 G 检查点）。
- Loss 自动判停（LossJudge）：逐 epoch 解析引擎 train.log 主损失并判定拟合状态，
  命中 converged / overfit_risk → trainer.stop_training()。主损失索引以引擎实码为准：
  * sovits：engines/so-vits-svc-4.1-Stable/train.py:249
    ``losses = [loss_disc, loss_gen, loss_fm, loss_mel, loss_kl]`` → 取 index 3
    （loss_mel，mel 重建 L1×c_mel，SVC 音质主损失）；日志行格式为
    ``<asctime>\\t<name>\\tINFO\\tLosses: [...], step: N, lr: ...``（utils.get_logger
    formatter ``%(asctime)s\\t%(name)s\\t%(levelname)s\\t%(message)s``），
    epoch 归属取同日志最近一条 ``Train Epoch: N`` 行；
  * melotts：engines/MeloTTS/melo/train.py:466
    ``losses = [loss_disc, loss_gen, loss_fm, loss_mel, loss_dur, loss_kl]``，
    train.py:452 ``loss_gen_all = loss_gen + loss_fm + loss_mel + loss_dur + loss_kl``
    → 生成器总损失 = 列表 index 1 起求和（index 0 为 discriminator 项，剔除）；
    日志行 train.py:472 为 ``[x.item() for x in losses] + [global_step, lr]``
    （末两位是 step 与 lr，解析时剥离），epoch 边界用 train.py:555 的
    ``====> Epoch: N`` 收尾行。
- 检查点保障（优雅停止）：判停命中后写 .stop_requested 哨兵文件到模型目录，
  引擎（train.py 已打补丁）在下一个 epoch 边界先存盘再退出；超时未退出才兜底强杀
  （stop_training，产物取最近一次 eval_interval 检查点）。不再强制调小 eval_interval
  —— 那会导致每 epoch 写 GB 级检查点、GPU 长时间等盘空载。
- 判停主循环轮询间隔 _TRAIN_POLL_SECONDS（默认 5s；测试注入更小值）；
  语料任务进度轮询间隔 _CORPUS_POLL_SECONDS。
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

MODEL_TYPE_MELOTTS = "melotts"
MODEL_TYPE_SOVITS = "sovits"
_SUPPORTED_MODEL_TYPES = (MODEL_TYPE_MELOTTS, MODEL_TYPE_SOVITS)

# 阶段清单（冻结顺序，前端按此渲染进度）
STAGE_IDS = ("reference", "corpus", "preprocess", "training", "collect")

# 输出模型名白名单（与两 trainer 的 _OUTPUT_NAME_PATTERN 同口径：字母/数字/下划线/连字符）
_OUTPUT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

# 判停准则常量（spec 冻结默认值；judge 入参可覆盖）
CONVERGED_WINDOW = 3        # K：连续 K 个 epoch 满足条件即判停
CONVERGED_EPSILON = 0.01    # ε：相对前窗改善 <1% 视为停滞
OVERFIT_DELTA = 0.10        # δ：较历史最优回升 >10% 视为过拟合风险
MIN_EPOCHS = 3              # 最少训练 epoch 数，此前不判停
# 成片模式下「每片需要的短句条数」经验值：5~15s 切片平均约 2.7 句/片，取 2.8
# 保证拼片后片数 ≥ 目标（拼片按 ≥5s 收片，句长随音色/语速波动）
_TEXTS_PER_CLIP = 2.8
_CORPUS_POOL_MAX = 30000    # 默认语料池上限（≈10000 片所需句数）

# 默认语料文本集（≥16 条中文短句；覆盖常用声母/韵母/声调与陈述/疑问/感叹/祈使/
# 数字/日期等句式，请求 texts 可整体覆盖）
DEFAULT_CORPUS_TEXTS: list[dict] = [
    {"text": "你好，很高兴认识你，希望我们合作愉快。"},
    {"text": "今天天气真不错，我们一起出去走走吧。"},
    {"text": "人工智能正在改变我们的生活方式。"},
    {"text": "请问去火车站怎么走？沿着这条路一直向前就到了。"},
    {"text": "春天来了，公园里的花开得非常漂亮。"},
    {"text": "请把数字一七八二四六再重复一遍。"},
    {"text": "这家餐厅的红烧肉做得特别地道。"},
    {"text": "学习使人进步，骄傲使人落后。"},
    {"text": "明天上午九点，我们在公司门口集合。"},
    {"text": "世界的美好，需要我们用心去发现。"},
    {"text": "他的普通话非常标准，声音也很洪亮。"},
    {"text": "科技创新是推动社会进步的重要力量。"},
    {"text": "小溪的水清澈见底，鱼儿游来游去。"},
    {"text": "妈妈做的饭菜，永远是最美味的。"},
    {"text": "人生就像一场旅行，不必在乎目的地。"},
    {"text": "读书使人充实，讨论使人机智。"},
    {"text": "绿水青山就是金山银山。"},
    {"text": "云计算与大数据正在深度融合。"},
    {"text": "祝你生日快乐，天天都有好心情！"},
    {"text": "二零二六年十月十七日，星期六。"},
]

def _generated_corpus_texts(limit: int = 400) -> list[dict]:
    """模板组合出至多 limit 条唯一中文句子（补充内置池）。

    说明：模板句的语义多样性弱于人工语料，但覆盖常用音节/数字/疑问/祈使节奏；
    默认池按目标片数放大（见 _default_corpus_texts），请求的 texts 可整体覆盖。
    """
    times = ["今天", "昨天", "明天", "早上", "中午", "下午", "晚上", "周末", "这周一", "下个月",
             "春天", "夏天", "秋天", "冬天", "下雨的时候", "放假以后", "开学之前", "晚上八点"]
    places = ["公园", "图书馆", "火车站", "超市", "学校", "医院", "公司", "家里", "餐厅", "海边",
              "山上", "街角", "地铁站", "电影院", "博物馆", "菜市场", "咖啡馆", "银行"]
    activities = ["散步", "看书", "等车", "买菜", "上课", "加班", "做饭", "喝茶", "拍照", "听音乐",
                  "跑步", "洗衣服", "整理房间", "写作业", "和朋友聊天", "骑车", "看电影", "逛商场"]
    feelings = ["很好", "很不错", "有点累", "很放松", "特别满足", "有些紧张", "格外平静", "轻松了不少"]
    friends = ["我的朋友", "同事小李", "隔壁阿姨", "老师", "妈妈", "哥哥", "邻居", "店里的老板"]
    news = ["附近新开了一家面馆", "明天可能要下雨", "周末有一场音乐会", "公司下个月要搬新地址",
            "这条路最近在修", "图书馆延长了开放时间", "公交车改路线了", "小区里新装了路灯"]
    plans = ["去看一场电影", "学做几道新菜", "把房间彻底打扫一遍", "陪家人出去走走",
             "报名一个兴趣班", "整理这一年的照片", "去郊外骑车", "把没读完的书看完"]
    conditions = ["时间来得及", "天气不太冷", "工作提前做完", "路上不堵车", "身体舒服一些",
                  "朋友也有空", "预算还够用", "雨停下来"]
    things = ["外套", "书包", "杯子", "椅子", "手机", "围巾", "台灯", "笔记本", "雨伞", "耳机"]
    adjs = ["干净", "结实", "轻便", "好看", "舒服", "便宜", "暖和", "精致"]
    comments = ["我很喜欢", "可以考虑一下", "颜色也很合适", "价格还算公道", "用起来挺方便", "正好需要"]
    minutes = ["五分钟", "十分钟", "十五分钟", "二十分钟", "半个小时", "四十分钟"]
    actions = ["出发", "集合", "开始吃饭", "去看展", "到楼下等", "准备出门", "把东西收拾好", "一起拍照"]
    animals = ["小猫", "小狗", "麻雀", "鸽子", "兔子", "金鱼"]
    animal_actions = ["趴在窗台上", "在草地上跑", "停在树枝上", "在水里游", "安静地坐着", "追着自己的尾巴"]
    requests = ["把窗户关一下", "帮我拿一杯水", "把音量调小一点", "稍等我几分钟",
                "把这份文件打印出来", "再说一遍", "把灯打开", "把门带上"]
    reminders = ["带一把伞", "多穿一件衣服", "早点回家", "路上注意安全", "记得吃早饭",
                 "把手套戴上", "别忘记带钥匙", "出门前检查一下钱包"]
    reasons = ["它让我觉得很放松", "用起来特别顺手", "味道让人想起小时候", "身边的人都推荐",
               "它安静又舒服", "每次看到心情都会变好"]
    events = ["下了一场大雨", "有人敲门", "电话响了两次", "外面放起了烟花", "楼下的花开了",
              "快递送到了", "小区停电了", "风突然变大了"]
    states = ["路面有点湿", "屋里很安静", "外面已经放晴", "我正准备出门", "大家都在休息", "街上人不多"]
    routes = ["沿着这条路一直向前就到了", "坐两站地铁再走五分钟", "过了红绿灯右转",
              "在下一个路口左拐", "出门坐公交车比较快", "穿过小广场就能看到", "跟着人群走就行"]
    quotes = ["这件事别着急", "我们已经准备好了", "明天见面再细聊", "记得带上证件",
              "他最近状态不错", "这个办法挺管用"]
    prices = ["二十", "三十五", "五十", "八十", "一百", "一百二"]
    rain_words = ["可能", "大概", "说不定"]

    seen: dict[str, None] = {}

    def add(text: str) -> None:
        text = text.strip()
        if 10 <= len(text) <= 45 and text not in seen:
            seen[text] = None

    for _ in range(max(3000, limit * 4)):
        add(f"{random.choice(times)}，我{random.choice(activities)}，心情{random.choice(feelings)}。")
        add(f"请问{random.choice(places)}怎么走？{random.choice(routes)}。")
        add(f"{random.choice(friends)}告诉我，{random.choice(news)}。")
        add(f"我打算{random.choice(plans)}，不过{random.choice(conditions)}。")
        add(f"这件{random.choice(things)}看起来{random.choice(adjs)}，{random.choice(comments)}。")
        add(f"再过{random.choice(minutes)}，我们{random.choice(actions)}。")
        add(f"如果{random.choice(conditions)}，我们就{random.choice(actions)}。")
        add(f"{random.choice(animals)}{random.choice(animal_actions)}，看起来很可爱。")
        add(f"请您{random.choice(requests)}，谢谢。")
        add(f"{random.choice(times)}{random.choice(rain_words)}会下雨，{random.choice(reminders)}。")
        add(f"我最喜欢{random.choice(things)}，因为{random.choice(reasons)}。")
        add(f"刚才{random.choice(events)}，现在{random.choice(states)}。")
        add(f"{random.choice(places)}里的人说，{random.choice(quotes)}。")
        add(f"这件{random.choice(things)}要{random.choice(prices)}块钱，{random.choice(comments)}。")
        p1, p2 = random.sample(places, 2)
        add(f"从{p1}到{p2}大概要{random.choice(minutes)}。")

    pool = sorted(seen)
    random.Random(20261024).shuffle(pool)
    return [{"text": text} for text in pool[:limit]]


# 扩展语料池（唯一句子，成片模式按需截断）：默认 20 条 + 人工扩充 ~180 条（覆盖
# 日常/工作/科技/出行/美食/天气/数字/日期/疑问/感叹/祈使等句式）+ 模板生成 400 条。
EXTENDED_CORPUS_TEXTS: list[dict] = DEFAULT_CORPUS_TEXTS + [
    {"text": "清晨的阳光洒在窗台上，新的一天开始了。"},
    {"text": "请问今天的会议改到下午三点了吗？"},
    {"text": "记得出门前检查一下钥匙和手机。"},
    {"text": "这本书我看了三遍，每次都有新的收获。"},
    {"text": "外面下起了小雨，记得带伞。"},
    {"text": "地铁上人不多，我们坐最后一个座位吧。"},
    {"text": "他们的团队今年拿到了行业大奖。"},
    {"text": "请把这份报告在周五之前发给我。"},
    {"text": "咖啡要大杯还是中杯？"},
    {"text": "山上的空气特别清新，深呼吸一口整个人都精神了。"},
    {"text": "银行门口的台阶有点滑，走路当心。"},
    {"text": "孩子放学后在院子里踢球，笑声传得很远。"},
    {"text": "这道数学题的解法其实很简单。"},
    {"text": "导航显示前方五百米右转。"},
    {"text": "我最喜欢的季节是秋天，天高气爽。"},
    {"text": "经过半年的努力，项目终于顺利上线了。"},
    {"text": "麻烦帮我把空调温度调低两度。"},
    {"text": "菜市场里的西红柿又新鲜又便宜。"},
    {"text": "他弹钢琴的样子特别专注。"},
    {"text": "飞机预计二十分钟后降落。"},
    {"text": "人生没有白走的路，每一步都算数。"},
    {"text": "周末我们去看电影还是逛书店？"},
    {"text": "这批货的质量检验全部合格。"},
    {"text": "你听，远处的钟声敲了八下。"},
    {"text": "奶奶种的月季花开满了整个院子。"},
    {"text": "会议室已经预订到明天上午十点。"},
    {"text": "注意身体，别总是熬夜加班。"},
    {"text": "高铁的速度真是快，转眼就到了下一座城市。"},
    {"text": "请出示您的健康码和身份证。"},
    {"text": "这段旋律一响起，很多人都会跟着哼唱。"},
    {"text": "今天的晚饭我做了一个新菜，你尝尝。"},
    {"text": "明天的气温会降到零下三度，记得添衣服。"},
    {"text": "图书馆里安静得只能听见翻书的声音。"},
    {"text": "他的演讲赢得了全场热烈的掌声。"},
    {"text": "新买的台灯有三档亮度可以调节。"},
    {"text": "公交车每十分钟一班，不用等太久。"},
    {"text": "我们的目标是把服务做到极致。"},
    {"text": "这条小巷的尽头有一家很棒的面馆。"},
    {"text": "数据表明，用户满意度提升了百分之十五。"},
    {"text": "别急，慢慢说，把事情讲清楚。"},
    {"text": "海边的日落美得让人不想离开。"},
    {"text": "包裹交付时间定在下周一上午。"},
    {"text": "小猫蜷在沙发上睡得正香。"},
    {"text": "他一口气跑了五公里，脸不红气不喘。"},
    {"text": "请各位佩戴好工牌后再进入车间。"},
    {"text": "这批学生的毕业设计质量非常高。"},
    {"text": "手机没电了，借你的充电器用一下。"},
    {"text": "旧书店里藏着不少绝版的宝贝。"},
    {"text": "冬天的第一场雪比往年来得早了一些。"},
    {"text": "请核对账单上的每一项金额。"},
    {"text": "机场大巴整点发车，路上大约四十分钟。"},
    {"text": "秋天是丰收的季节，田野里一片金黄。"},
    {"text": "这家公司的研发投入连年增长。"},
    {"text": "雨后的彩虹横跨整片山谷。"},
    {"text": "麻烦您在这里签个字确认。"},
    {"text": "训练有素的导盲犬带着主人穿过马路。"},
    {"text": "这张照片是三年前在洱海边拍的。"},
    {"text": "医生叮嘱他每天至少喝八杯水。"},
    {"text": "过马路请走斑马线，注意来往车辆。"},
    {"text": "硬盘里的备份文件终于找齐了。"},
    {"text": "今年的桂花开得比往年更盛，香气扑鼻。"},
    {"text": "服务员，麻烦再来一碗米饭。"},
    {"text": "天文学家用望远镜观测到了新的彗星。"},
    {"text": "他的回答简洁有力，赢得满堂喝彩。"},
    {"text": "请保持安静，考试正在进行中。"},
    {"text": "地铁末班车是晚上十一点整。"},
    {"text": "小和尚挠挠头，露出一脸疑惑。"},
    {"text": "厨房里飘出阵阵饭菜的香味。"},
    {"text": "本次列车开往北京南站。"},
    {"text": "创新创业大赛的报名截止到月底。"},
    {"text": "爷爷的毛笔字写得苍劲有力。"},
    {"text": "别忘了给花浇水，它们两天没喝水了。"},
    {"text": "这套系统支持多语言实时翻译。"},
    {"text": "演出八点开始，我们七点半入场。"},
    {"text": "山路十八弯，司机开得又稳又慢。"},
    {"text": "她的笑容像春天的阳光一样温暖。"},
    {"text": "请把垃圾分好类再投放到对应的桶里。"},
    {"text": "这个结论还需要更多实验数据支撑。"},
    {"text": "候车室里，旅客们秩序井然地排队检票。"},
    {"text": "他收藏了一百多枚各式各样的邮票。"},
    {"text": "台风预警升级，渔船全部回港避风。"},
    {"text": "今天的日程排得很满，晚上还要加班。"},
    {"text": "一杯热茶下肚，浑身都暖和了。"},
    {"text": "请下载最新版本的客户端并安装。"},
    {"text": "博物馆的青铜器展区今天免费开放。"},
    {"text": "小妹妹数着一二三四五，学得特别认真。"},
    {"text": "风把窗帘吹得轻轻飘起来。"},
    {"text": "这家工厂实现了全自动化生产。"},
    {"text": "赛后采访中，队员们感谢了教练的付出。"},
    {"text": "您反馈的问题我们会在二十四小时内处理。"},
    {"text": "菜市场的吆喝声此起彼伏。"},
    {"text": "这场雨下了整整一夜。"},
    {"text": "他用三行代码解决了困扰团队一周的问题。"},
    {"text": "站台上的广播提醒旅客注意脚下空隙。"},
    {"text": "爷爷给我讲他年轻时候的故事。"},
    {"text": "这个价位能买到这样的配置已经很划算了。"},
    {"text": "请勿在展厅内使用闪光灯拍照。"},
    {"text": "晚霞把湖面染成了金红色。"},
    {"text": "新学期第一课，老师讲了时间管理。"},
    {"text": "电梯正在维修，请走旁边的楼梯。"},
    {"text": "司机师傅熟练地倒车入库。"},
    {"text": "仓库里的货物按批次码放得整整齐齐。"},
    {"text": "请提前十分钟到达面试地点。"},
    {"text": "这是一场跨越三千公里的奔赴。"},
    {"text": "冰淇淋在夏天永远最受欢迎。"},
    {"text": "手机支付已经成为日常生活的习惯。"},
    {"text": "他把失败当作下一次尝试的起点。"},
    {"text": "园林里的假山流水布置得十分巧妙。"},
    {"text": "报告显示城市空气质量持续改善。"},
    {"text": "请旅客朋友保管好随身物品。"},
    {"text": "观众席上响起了经久不息的掌声。"},
    {"text": "这份合同的关键条款需要再确认一遍。"},
    {"text": "田径场上，运动员们正在做热身运动。"},
    {"text": "清晨五点的城市还没有醒来。"},
    {"text": "网购的商品第二天就送到了。"},
    {"text": "她把散落的花瓣夹进了日记本。"},
    {"text": "请各位代表依次上台领奖。"},
    {"text": "电台里播放着舒缓的爵士乐。"},
    {"text": "这只机械臂能完成毫米级精度的操作。"},
    {"text": "门口的梧桐树叶落了一地。"},
    {"text": "面试官问了一个很刁钻的问题。"},
    {"text": "会前请把手机调成静音模式。"},
    {"text": "这锅汤熬了整整三个小时。"},
    {"text": "孩子们在沙滩上堆起了一座城堡。"},
    {"text": "客服电话二十四小时都有人接听。"},
    {"text": "他把伞塞到我手里，自己淋着雨跑了。"},
    {"text": "体检报告显示各项指标都正常。"},
    {"text": "黄山的日出值得凌晨四点起床。"},
    {"text": "请遵守实验室的安全操作规范。"},
    {"text": "木匠手里的刨子推出一卷卷花屑。"},
    {"text": "昨晚的球赛踢到了最后一分钟才分出胜负。"},
    {"text": "超市的促销活动到周日截止。"},
    {"text": "这趟旅行我们计划了整整半年。"},
    {"text": "她的字迹工整得像打印出来的一样。"},
    {"text": "电梯里遇到了隔壁部门的新同事。"},
    {"text": "城市夜幕降临，霓虹灯次第亮起。"},
    {"text": "请将您的座椅靠背调整到直立位置。"},
    {"text": "面包刚出炉，香气弥漫了整条街。"},
    {"text": "团队复盘会上大家畅所欲言。"},
    {"text": "老街的石板路被岁月磨得发亮。"},
    {"text": "邮寄的包裹三天后就能到达。"},
    {"text": "这次培训共有两百人报名参加。"},
    {"text": "请检查网络连接后重试。"},
    {"text": "秋天的稻田像铺了一层金子。"},
    {"text": "他把这个单词拼错了两次。"},
    {"text": "水果摊的老板热情地招呼客人尝一尝。"},
    {"text": "监理工程师对每道工序都严格把关。"},
    {"text": "夜市的小吃摊一直营业到凌晨两点。"},
    {"text": "这本词典的附录特别实用。"},
    {"text": "请系好安全带，飞机即将起飞。"},
    {"text": "小狗见到主人，摇着尾巴飞奔过来。"},
    {"text": "文件已经上传到共享盘的指定目录。"},
    {"text": "社区志愿者每周六上午打扫楼道。"},
    {"text": "这批新书下周上架，欢迎借阅。"},
    {"text": "他把困惑写在纸条上递给老师。"},
    {"text": "电池续航从六小时提升到了十小时。"},
    {"text": "请隔着门缝先看看外面有没有人。"},
    {"text": "山顶的寺庙传来悠远的钟声。"},
    {"text": "会议纪要将在今天下班前发出。"},
    {"text": "地铁一号线的终点站是森林公园。"},
    {"text": "她把教室的每一扇窗都擦得透亮。"},
    {"text": "拼图只剩最后一块就完成了。"},
    {"text": "您拨打的电话正在通话中，请稍后再拨。"},
    {"text": "清明时节，山上的杜鹃花开了。"},
    {"text": "快递小哥冒着大雨送来了包裹。"},
    {"text": "这个功能在内测阶段收到了大量好评。"},
    {"text": "他把桌上的账本一页页核对清楚。"},
    {"text": "请各位乘客从后门下车。"},
    {"text": "冬泳爱好者们破冰入水，精神抖擞。"},
    {"text": "这份地图标注了全线十二个景点。"},
    {"text": "阳光透过树叶洒下斑驳的光影。"},
    {"text": "请排队取号，按顺序办理业务。"},
    {"text": "编程的魅力在于把想法变成现实。"},
    {"text": "爷爷把菜园打理得井井有条。"},
    {"text": "欢迎乘坐本次航班，祝您旅途愉快。"},
    {"text": "孩子们的画展下月在美术馆开幕。"},
    {"text": "他把硬币投进许愿池，闭眼许了个愿。"},
    {"text": "这项技术能把废料转化成建筑材料。"},
    {"text": "请核对车次和座位号再上车。"},
    {"text": "厨房的抽油烟机该清洗了。"},
    {"text": "运动之后记得做拉伸放松肌肉。"},
    {"text": "她在琴房练到深夜，指尖都磨出了茧。"},
    {"text": "这笔奖学金缓解了全家的压力。"},
    {"text": "提醒您，前方到站需要换乘二号线。"},
] + _generated_corpus_texts()


def _default_corpus_texts(target_clips: Optional[int] = None) -> list[dict]:
    """默认语料池：按目标片数放大（约 2.8 句/片），上限 _CORPUS_POOL_MAX。

    小目标直接复用内置扩展池；目标较大时追加模板生成句，保证片数可达目标。
    """
    base = [dict(item) for item in EXTENDED_CORPUS_TEXTS]
    if not target_clips:
        return base
    need = min(_CORPUS_POOL_MAX, int(target_clips * _TEXTS_PER_CLIP))
    if need <= len(base):
        return base
    seen = {item["text"] for item in base}
    for item in _generated_corpus_texts(need):
        if len(base) >= need:
            break
        if item["text"] not in seen:
            base.append(item)
            seen.add(item["text"])
    return base

# 轮询间隔（秒）：语料任务进度 / 训练日志判停（测试可 patch 为更小值）
_CORPUS_POLL_SECONDS = 0.1
_TRAIN_POLL_SECONDS = 5.0

# 用户自带数据集导入（sovits）：音频扩展名白名单、统一转码目标采样率、最少条数
# （≥2：训练/验证切分各需至少 1 条）。导入统一转码为 44.1kHz 单声道 PCM16 wav，
# 与引擎预处理链路（hubert/f0 按 44.1k）对齐；参考工作流为 5~15s 切片 wav。
_IMPORT_AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".flac", ".ogg"})
_IMPORT_SAMPLE_RATE = 44100
_IMPORT_MIN_CLIPS = 2


class _ImportAudioError(ValueError):
    """用户音频数据集导入失败（消息直接透出为 corpus 阶段失败原因）。"""

# 优雅停止（GPU 空载治理）：判停命中后写哨兵文件 .stop_requested 到模型目录，
# 引擎在下一个 epoch 边界先落盘检查点再退出（train.py 已打补丁）；期间训练照常
# 占用 GPU，不再靠「每 epoch 存检查点」保障产物（那是判停初版的写盘阻塞根因）。
# 超时未优雅退出（旧引擎副本/异常）才兜底强杀，产物取最近一次 eval_interval 检查点。
_STOP_SENTINEL_NAME = ".stop_requested"
_STOP_FALLBACK_SECONDS = 600.0

# 自然到顶路径的存盘节拍：eval_interval 上限 + 目标存盘次数规划。
# 官方 prep 配置的 eval_interval（如 1000 步）可能大于短训练总步数，导致全程
# 只有初始检查点；此处按「总步数/10」规划（10 个存盘点），既保证到顶时检查点
# 足够新鲜，又把 GB 级写盘摊薄到分钟级间隔（不复现每 epoch 写盘的 GPU 空载）。
_EVAL_INTERVAL_CAP = 1000
_CHECKPOINT_TARGET_SAVES = 10


def _planned_eval_interval(epochs: int, n_texts: int) -> int:
    """规划训练配置 eval_interval（步）：min(上限, ceil(总步数/目标存盘次数))。

    总步数按最坏 batch（16，melotts/sovits 自适应上限）保守估计——实际 batch 更小
    则步更多，存盘更频繁，只会更安全。
    """
    steps_per_epoch = max(1, -(-max(1, n_texts) // 16))
    total_steps = max(1, epochs) * steps_per_epoch
    return max(1, min(_EVAL_INTERVAL_CAP, -(-total_steps // _CHECKPOINT_TARGET_SAVES)))


def _import_audio_dataset(src: Path, dst: Path) -> int:
    """导入用户音频数据集：统一转码 44.1kHz 单声道 PCM16 wav 落 dst/<序号>.wav。

    递归扫描 src 下白名单扩展名音频；单个文件解码失败跳过并记日志；全部不可
    解码时抛 _ImportAudioError。返回成功写入条数。同步阻塞函数，调用方须经
    asyncio.to_thread 执行（数千条导入耗时数十秒，不可阻塞事件循环）。
    """
    import math

    import soundfile as sf
    from scipy.signal import resample_poly

    files = sorted(
        p for p in src.rglob("*")
        if p.is_file() and p.suffix.lower() in _IMPORT_AUDIO_EXTENSIONS
    )
    if not files:
        raise _ImportAudioError(
            f"源目录下未找到音频文件（支持 {'/'.join(sorted(_IMPORT_AUDIO_EXTENSIONS))}）: {src}"
        )
    dst.mkdir(parents=True, exist_ok=True)
    written = 0
    for path in files:
        try:
            data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        except Exception as exc:
            logger.warning("导入跳过不可解码音频 %s: %s", path, exc)
            continue
        if data.size == 0:
            logger.warning("导入跳过空音频 %s", path)
            continue
        mono = data.mean(axis=1)  # 多声道混为单声道
        if sr != _IMPORT_SAMPLE_RATE:
            g = math.gcd(int(sr), _IMPORT_SAMPLE_RATE)
            mono = resample_poly(mono, _IMPORT_SAMPLE_RATE // g, int(sr) // g)
        sf.write(str(dst / f"{written + 1:06d}.wav"), mono, _IMPORT_SAMPLE_RATE, subtype="PCM_16")
        written += 1
    if written < 1:
        raise _ImportAudioError("没有可导入的音频（所有文件解码失败）")
    return written


def _now_iso() -> str:
    """本地时区 ISO8601 时间戳（秒级）"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Loss 解析与判停（纯函数，独立可测）
# ---------------------------------------------------------------------------

# sovits 主损失索引：train.py:249 losses=[loss_disc, loss_gen, loss_fm, loss_mel, loss_kl]
# → index 3 = loss_mel（mel 重建 L1，SVC 音质主损失）
_SOVITS_MEL_LOSS_INDEX = 3
_SOVITS_EPOCH_RE = re.compile(r"Train Epoch:\s*(\d+)")
_SOVITS_LOSSES_RE = re.compile(r"Losses:\s*\[([^\[\]]+)\]")
# melotts 损失行：消息体为损失列表 repr（utils.get_logger formatter 制表符分隔，
# levelname=INFO）；行尾即列表收口，避免误匹配其他 INFO 行
_MELOTTS_LOSS_LINE_RE = re.compile(r"\tINFO\t(\[[^\[\]]+\])\s*$")
_MELOTTS_EPOCH_BOUNDARY_RE = re.compile(r"====> Epoch:\s*(\d+)")
# 兜底用：日志中任意 epoch 标记行（判停器在无损失行时按 epoch 数回填 max_epochs）
_ANY_EPOCH_MARK_RE = re.compile(r"(?:====> Epoch|Train Epoch):\s*(\d+)")


def parse_sovits_train_log(log_text: str) -> list[tuple[int, float]]:
    """解析 so-vits train.log，返回逐 epoch 的主损失（mel 项，index=3）均值序列。

    epoch 归属：日志逐行扫描，``Train Epoch: N`` 行更新当前 epoch，
    其后的 ``Losses: [...], step: ...`` 行计入该 epoch；同 epoch 多条取均值。
    Returns:
        [(epoch, mean_loss), ...] 按 epoch 升序
    """
    buckets: dict[int, list[float]] = {}
    current_epoch = 0
    for line in log_text.splitlines():
        m = _SOVITS_EPOCH_RE.search(line)
        if m:
            current_epoch = int(m.group(1))
            continue
        m = _SOVITS_LOSSES_RE.search(line)
        if m:
            try:
                values = [float(x) for x in m.group(1).split(",") if x.strip()]
            except ValueError:
                continue
            if current_epoch > 0 and len(values) > _SOVITS_MEL_LOSS_INDEX:
                buckets.setdefault(current_epoch, []).append(values[_SOVITS_MEL_LOSS_INDEX])
    return [(epoch, sum(v) / len(v)) for epoch, v in sorted(buckets.items())]


def parse_melotts_train_log(log_text: str) -> list[tuple[int, float]]:
    """解析 MeloTTS train.log，返回逐 epoch 的生成器总损失均值序列。

    - 损失行：消息体为列表 repr（train.py:472），末两位为 global_step 与 lr，
      剥离后为损失分量；生成器总损失 = 除 index 0（discriminator）外求和
      （train.py:452 实码）。
    - epoch 边界：``====> Epoch: N`` 为 epoch N 收尾行（train.py:555），
      其之前的未闭合损失行计入 epoch N；日志尾部未闭合的损失行归属下一 epoch
      （训练进行中的部分 epoch）。
    Returns:
        [(epoch, mean_loss), ...] 按 epoch 升序
    """
    buckets: dict[int, list[float]] = {}
    pending: list[float] = []
    closed_epoch = 0  # 最近一次 boundary 的编号；尚无 boundary 时损失行属于 epoch 1
    for line in log_text.splitlines():
        m = _MELOTTS_EPOCH_BOUNDARY_RE.search(line)
        if m:
            epoch = int(m.group(1))
            if pending:
                buckets.setdefault(epoch, []).extend(pending)
                pending = []
            closed_epoch = epoch
            continue
        m = _MELOTTS_LOSS_LINE_RE.search(line)
        if m:
            try:
                values = [float(x) for x in m.group(1).strip("[]").split(",") if x.strip()]
            except ValueError:
                continue
            components = values[:-2]  # 剥离末两位 global_step 与 lr
            if len(components) >= 2:
                pending.append(sum(components[1:]))  # 生成器总损失（剔除 discriminator 项）
    if pending:
        buckets.setdefault(closed_epoch + 1, []).extend(pending)
    return [(epoch, sum(v) / len(v)) for epoch, v in sorted(buckets.items())]


def judge_losses(
    epoch_losses: list[tuple[int, float]],
    max_epochs: int,
    *,
    converged_window: int = CONVERGED_WINDOW,
    converged_epsilon: float = CONVERGED_EPSILON,
    overfit_delta: float = OVERFIT_DELTA,
    min_epochs: int = MIN_EPOCHS,
) -> tuple[str, Optional[str]]:
    """按逐 epoch 主损失序列判定拟合状态。

    Returns:
        (fitting_status, stop_reason|None)：
        - max_epochs：已解析到的最大 epoch 达到上限（由引擎自然结束）；
        - overfit_risk：较历史最优回升 > δ 且持续 K 个 epoch（优先于 converged）；
        - converged：连续 K 个 epoch 相对前窗（前 K 个 epoch 均值）改善 < ε；
        - improving：其余（含 epoch 数不足 min_epochs 的保护区间，不判停）。
    """
    values = [loss for _, loss in sorted(epoch_losses)]
    n = len(values)
    if n == 0:
        return "improving", None
    last_epoch = max(epoch for epoch, _ in epoch_losses)
    if max_epochs > 0 and last_epoch >= max_epochs:
        return "max_epochs", f"已解析到 epoch {last_epoch}，达到本次训练上限（{max_epochs}）"
    if n < min_epochs:
        return "improving", None  # min_epochs 保护区间内不判停

    if n >= converged_window:
        # overfit_risk：最后 K 个 epoch 各自较其之前的历史最优回升均 > δ（连续）
        overfit_streak = 0
        for i in range(n - converged_window, n):
            history = values[:i]
            best = min(history) if history else None
            if best is None or best <= 1e-12:
                break
            if (values[i] - best) / best > overfit_delta:
                overfit_streak += 1
            else:
                break
        if overfit_streak >= converged_window:
            return (
                "overfit_risk",
                f"主损失较历史最优回升超过 {overfit_delta:.0%} 且持续 {converged_window} 个 epoch",
            )

        # converged：最后 K 个 epoch 各自相对前窗（前 K 个 epoch 均值）改善均 < ε（连续）
        converged_streak = 0
        for i in range(n - converged_window, n):
            window = values[max(0, i - converged_window):i]
            if not window:
                break
            prev_mean = sum(window) / len(window)
            improvement = (prev_mean - values[i]) / prev_mean if prev_mean > 1e-12 else 0.0
            if improvement < converged_epsilon:
                converged_streak += 1
            else:
                break
        if converged_streak >= converged_window:
            return (
                "converged",
                f"连续 {converged_window} 个 epoch 相对前窗改善不足 {converged_epsilon:.0%}",
            )
    return "improving", None


class LossJudge:
    """引擎训练日志主损失判停器（解析 + 判定，纯函数无 IO，独立可测）。"""

    def __init__(self, engine: str):
        if engine not in _SUPPORTED_MODEL_TYPES:
            raise ValueError(f"Unsupported engine for LossJudge: {engine!r}")
        self._engine = engine

    def parse(self, log_text: str) -> list[tuple[int, float]]:
        """解析日志全文为逐 epoch 主损失序列。"""
        if self._engine == MODEL_TYPE_SOVITS:
            return parse_sovits_train_log(log_text)
        return parse_melotts_train_log(log_text)

    def judge(
        self, epoch_losses: list[tuple[int, float]], max_epochs: int
    ) -> tuple[str, Optional[str]]:
        """按损失序列判定拟合状态，返回 (fitting_status, stop_reason|None)。"""
        return judge_losses(epoch_losses, max_epochs)

    def judge_log(self, log_text: str, max_epochs: int) -> tuple[str, Optional[str]]:
        """解析 + 判定一步完成。"""
        return self.judge(self.parse(log_text), max_epochs)


# ---------------------------------------------------------------------------
# 编排服务
# ---------------------------------------------------------------------------


class PipelineRunConflictError(RuntimeError):
    """已有一键成模运行进行中（409 语义）。"""


class _StageError(Exception):
    """阶段失败（携带阶段标识与用户可读错误消息，由编排主流程统一落账）。"""

    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage
        self.message = message


def _normalize_texts(
    texts: Optional[list[dict]], target_clips: Optional[int] = None
) -> list[dict]:
    """语料文本归一化：缺省按目标片数取内置扩展语料池；请求覆盖时逐条校验非空。"""
    if not texts:
        return _default_corpus_texts(target_clips)
    normalized: list[dict] = []
    for i, item in enumerate(texts):
        text = item.get("text") if isinstance(item, dict) else None
        if not text or not str(text).strip():
            raise ValueError(f"texts[{i}].text must not be empty")
        normalized.append({"text": str(text)})
    return normalized


class AutoModelPipelineService:
    """一键成模编排服务：运行注册表（进程内 dict）+ 五阶段状态机。

    单 worker 部署语义（uvicorn --workers 1）；运行记录不跨进程共享。
    """

    def __init__(self) -> None:
        self._runs: dict[str, dict] = {}
        self._bg_tasks: dict[str, "asyncio.Task[None]"] = {}

    # ------------------------------------------------------------------
    # 提交与查询（公开接口）
    # ------------------------------------------------------------------

    async def submit_run(
        self,
        model_type: str,
        voice_description: Optional[str] = None,
        ref_audio_path: Optional[str] = None,
        texts: Optional[list[dict]] = None,
        output_name: Optional[str] = None,
        max_epochs: int = 10000,
        dataset_dir: Optional[str] = None,
        corpus_target_clips: Optional[int] = None,
    ) -> dict:
        """提交一键成模运行，创建 run 记录并起后台任务，立即返回状态快照。

        corpus_target_clips（语料目标切片条数，提示词/参考模式生效；自带数据集模式
        忽略）：给出时语料按句子边界组装为 5~15s 标准切片（长音频切分），缺省 None
        逐句直出。

        Raises:
            ValueError: model_type 非法 / 提示词、参考音频、数据集目录三选一校验失败 /
                        语料文本为空 / output_name 不在白名单 / max_epochs 非法 /
                        参考音频不在 data/input 白名单根下或文件不存在 /
                        dataset_dir 不存在或音频不足 / dataset_dir 与 melotts 组合 /
                        corpus_target_clips 非法
            PipelineRunConflictError: 已有运行进行中（409 语义）
        """
        if model_type not in _SUPPORTED_MODEL_TYPES:
            raise ValueError(
                f"Unsupported model_type: {model_type!r} (allowed: melotts / sovits)"
            )
        has_desc = bool(voice_description and str(voice_description).strip())
        has_ref = bool(ref_audio_path and str(ref_audio_path).strip())
        has_ds = bool(dataset_dir and str(dataset_dir).strip())
        if has_desc + has_ref + has_ds > 1:
            raise ValueError(
                "voice_description / ref_audio_path / dataset_dir 只能三选一，不可同时提供"
            )
        if has_desc + has_ref + has_ds == 0:
            raise ValueError(
                "voice_description / ref_audio_path / dataset_dir 必须三选一提供其一"
            )
        if has_ds and model_type != MODEL_TYPE_SOVITS:
            raise ValueError(
                "自带数据集模式当前仅支持 sovits 模型类型"
                "（MeloTTS 训练需要音频-文本对，请使用自动语料生成）"
            )

        if output_name is not None:
            output_name = str(output_name).strip()
            if not output_name or not _OUTPUT_NAME_PATTERN.match(output_name):
                raise ValueError(
                    f"Invalid output_name: {output_name!r}. "
                    "Only letters, digits, underscore and hyphen are allowed."
                )
        try:
            max_epochs = int(max_epochs)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid max_epochs: {max_epochs!r}")
        if max_epochs < 1:
            raise ValueError(f"max_epochs must be >= 1, got: {max_epochs}")
        if corpus_target_clips is not None:
            try:
                corpus_target_clips = int(corpus_target_clips)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid corpus_target_clips: {corpus_target_clips!r}")
            if corpus_target_clips < 1:
                raise ValueError(
                    f"corpus_target_clips must be >= 1, got: {corpus_target_clips}"
                )

        normalized_texts = _normalize_texts(texts, corpus_target_clips)

        if has_ref:
            self._validate_ref_audio_path(str(ref_audio_path))
        resolved_dataset_dir: Optional[str] = None
        if has_ds:
            resolved_dataset_dir = self._validate_dataset_dir(str(dataset_dir))

        # 运行级互斥：同一时间仅一个一键成模运行
        for run in self._runs.values():
            if run["status"] == "running":
                raise PipelineRunConflictError(
                    f"已有一键成模运行进行中: run_id={run['run_id']}"
                )

        run_id = uuid.uuid4().hex
        run = {
            "run_id": run_id,
            "status": "running",
            "model_type": model_type,
            "dataset_id": None,
            "stages": {sid: {"status": "pending", "detail": None} for sid in STAGE_IDS},
            "corpus": {"done": 0, "total": 0},
            "training": {
                "progress": 0.0,
                "epoch": 0,
                "total_epochs": max_epochs,
                "fitting_status": None,
                "stop_reason": None,
            },
            "result": None,
            "error": None,
        }
        self._runs[run_id] = run

        bg = asyncio.get_running_loop().create_task(
            self._execute(
                run,
                voice_description=str(voice_description).strip() if has_desc else None,
                ref_audio_path=str(ref_audio_path) if has_ref else None,
                texts=normalized_texts,
                output_name=output_name,
                max_epochs=max_epochs,
                dataset_dir=resolved_dataset_dir,
                corpus_target_clips=None if has_ds else corpus_target_clips,
            )
        )
        self._bg_tasks[run_id] = bg
        bg.add_done_callback(lambda t, rid=run_id: self._on_bg_done(rid, t))
        logger.info(
            "一键成模运行已提交: run_id=%s model_type=%s mode=%s max_epochs=%d",
            run_id,
            model_type,
            "prompt" if has_desc else ("dataset" if has_ds else "upload"),
            max_epochs,
        )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> Optional[dict]:
        """查询运行状态快照；run_id 不存在时返回 None。

        响应形状（冻结契约）：run_id / status(running|completed|failed) / model_type /
        dataset_id / stages([{id,status,detail}...]) / corpus({done,total}) /
        training({progress,epoch,total_epochs,fitting_status,stop_reason}) /
        result({model_name,model_dir,files})|null / error|null
        """
        run = self._runs.get(run_id)
        if run is None:
            return None
        return {
            "run_id": run["run_id"],
            "status": run["status"],
            "model_type": run["model_type"],
            "dataset_id": run["dataset_id"],
            "stages": [
                {
                    "id": sid,
                    "status": run["stages"][sid]["status"],
                    "detail": run["stages"][sid]["detail"],
                }
                for sid in STAGE_IDS
            ],
            "corpus": dict(run["corpus"]),
            "training": dict(run["training"]),
            "result": dict(run["result"]) if run["result"] else None,
            "error": run["error"],
        }

    # ------------------------------------------------------------------
    # 输入校验
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_ref_audio_path(ref_audio_path: str) -> None:
        """上传参考音频路径校验（fail-closed）：必须位于 input 白名单根之下且文件存在。"""
        from modelstation.config import get_settings

        settings = get_settings()
        root = Path(settings.sovits_svc.input_dir).resolve()
        try:
            resolved = Path(ref_audio_path).resolve()
        except Exception as exc:
            raise ValueError(f"Invalid ref_audio_path: {ref_audio_path}: {exc}")
        if not resolved.is_relative_to(root):
            raise ValueError(
                f"ref_audio_path must be located under {root}, got: {resolved}"
            )
        if not resolved.is_file():
            raise ValueError(f"ref_audio_path not found: {resolved}")

    @staticmethod
    def _validate_dataset_dir(dataset_dir: str) -> str:
        """自带数据集目录预校验（fail-closed）：目录存在且音频 ≥ _IMPORT_MIN_CLIPS。

        Returns:
            解析后的绝对路径（供后续导入阶段复用，避免二次解析漂移）。
        """
        src = Path(dataset_dir).expanduser()
        if not src.is_absolute():
            src = Path.cwd() / src
        try:
            resolved = src.resolve()
        except Exception as exc:
            raise ValueError(f"Invalid dataset_dir: {dataset_dir}: {exc}")
        if not resolved.is_dir():
            raise ValueError(f"dataset_dir 不存在或不是目录: {resolved}")
        audio_count = sum(
            1 for p in resolved.rglob("*")
            if p.is_file() and p.suffix.lower() in _IMPORT_AUDIO_EXTENSIONS
        )
        if audio_count < _IMPORT_MIN_CLIPS:
            raise ValueError(
                f"dataset_dir 音频不足（找到 {audio_count} 个），"
                f"至少需要 {_IMPORT_MIN_CLIPS} 个音频文件"
                f"（{'/'.join(sorted(_IMPORT_AUDIO_EXTENSIONS))}）"
            )
        return str(resolved)

    # ------------------------------------------------------------------
    # 后台主流程（每阶段 try/except，失败置 failed 并带 error，不抛出）
    # ------------------------------------------------------------------

    async def _execute(
        self,
        run: dict,
        *,
        voice_description: Optional[str],
        ref_audio_path: Optional[str],
        texts: list[dict],
        output_name: Optional[str],
        max_epochs: int,
        dataset_dir: Optional[str] = None,
        corpus_target_clips: Optional[int] = None,
    ) -> None:
        try:
            if dataset_dir:
                # 自带数据集模式：跳过参考音频/语料生成，导入本地音频即数据集
                ds_name = await self._stage_import_dataset(run, dataset_dir)
                n_clips = int(run["corpus"]["total"])
            else:
                ds_name = await self._stage_corpus(
                    run, voice_description, ref_audio_path, texts,
                    corpus_target_clips=corpus_target_clips,
                )
                # corpus.total 为最终成片口径（参考音频之外的数据条数）
                n_clips = max(0, int(run["corpus"]["total"]) - 1) or len(texts)
            await self._stage_preprocess(run, ds_name)
            model_name = await self._stage_training(
                run, ds_name, output_name, max_epochs, n_clips
            )
            self._stage_collect(run, model_name)
            run["status"] = "completed"
            logger.info(
                "一键成模运行完成: run_id=%s model=%s dataset=%s",
                run["run_id"], model_name, run["dataset_id"],
            )
        except asyncio.CancelledError:
            raise
        except _StageError as exc:
            self._fail_run(run, exc.stage, exc.message)
        except Exception as exc:  # 兜底：任何未预期异常都落账为 run failed
            logger.exception("一键成模运行未预期异常: run_id=%s", run["run_id"])
            self._fail_run(run, "collect", f"一键成模运行异常: {exc}")

    def _set_stage(self, run: dict, stage: str, status: str, detail: Optional[str] = None) -> None:
        run["stages"][stage]["status"] = status
        run["stages"][stage]["detail"] = detail

    def _fail_run(self, run: dict, stage: str, error: str) -> None:
        self._set_stage(run, stage, "failed", error)
        run["status"] = "failed"
        if not run["error"]:
            run["error"] = error
        logger.error(
            "一键成模运行失败: run_id=%s stage=%s error=%s", run["run_id"], stage, error
        )

    def _on_bg_done(self, run_id: str, task: "asyncio.Task[None]") -> None:
        """后台任务收尾：弹出注册；未捕获异常在此显式读取，避免 event loop 告警"""
        self._bg_tasks.pop(run_id, None)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("一键成模后台任务未捕获异常: run_id=%s error=%s", run_id, exc)

    # ------------------------------------------------------------------
    # 阶段 1+2：reference / corpus（提示词 / 上传 / 自带数据集三模式）
    # ------------------------------------------------------------------

    async def _stage_import_dataset(self, run: dict, dataset_dir: str) -> str:
        """corpus 阶段（自带数据集模式）：转码导入本地音频 → 登记 DS 编号。

        reference=skipped；导入统一转码 44.1kHz 单声道 wav（数千条耗时数十秒，
        经 asyncio.to_thread 执行避免阻塞事件循环）；corpus 计数即导入条数。
        """
        from modelstation.services import dataset_registry
        from modelstation.services.dataset_builder import resolve_datasets_root

        self._set_stage(run, "reference", "skipped", "自带数据集模式：无需生成参考音频")
        self._set_stage(run, "corpus", "running", "正在导入用户音频数据集（转码 44.1kHz 单声道）")
        try:
            registered = dataset_registry.register_dataset(
                engine="user_import", source_dir=dataset_dir
            )
        except dataset_registry.DatasetRegistryError as exc:
            raise _StageError("corpus", f"数据集编号分配失败: {exc}")
        run["dataset_id"] = registered["dataset_id"]
        ds_name = registered["name"]
        try:
            count = await asyncio.to_thread(
                _import_audio_dataset,
                Path(dataset_dir),
                resolve_datasets_root() / ds_name,
            )
        except _ImportAudioError as exc:
            raise _StageError("corpus", str(exc))
        except Exception as exc:
            raise _StageError("corpus", f"音频导入失败: {exc}")
        if count < _IMPORT_MIN_CLIPS:
            raise _StageError(
                "corpus", f"有效音频不足（导入 {count} 条），至少需要 {_IMPORT_MIN_CLIPS} 条"
            )
        run["corpus"]["done"] = count
        run["corpus"]["total"] = count
        self._set_stage(
            run,
            "corpus",
            "completed",
            f"数据集 {run['dataset_id']}（{ds_name}）导入完成"
            f"（{count} 条，已转码 44.1kHz 单声道 wav）",
        )
        return ds_name

    async def _stage_corpus(
        self,
        run: dict,
        voice_description: Optional[str],
        ref_audio_path: Optional[str],
        texts: list[dict],
        corpus_target_clips: Optional[int] = None,
    ) -> str:
        """corpus 阶段（含 reference 阶段语义），返回数据集目录名。

        提示词模式：reference=running（实际由 submit_pipeline 阶段一生成参考音频）；
        上传模式：reference=skipped。corpus 阶段进度从语料任务的 done/total 透出。
        corpus_target_clips 给出时（提示词/上传模式），语料生成后按句子边界组装
        5~15s 标准切片，计数器收敛为最终成片口径（含 reference）。
        """
        from modelstation.services.dataset_builder import (
            assemble_sentence_clips,
            count_corpus_entries,
            get_dataset_builder,
            resolve_dataset_dir,
        )

        builder = get_dataset_builder()
        if voice_description:
            self._set_stage(
                run, "reference", "running", "提示词模式：初始参考音频由统一流程阶段一生成"
            )
            self._set_stage(
                run, "corpus", "running", "统一流程语料生成进行中"
                + (f"（目标 {corpus_target_clips} 片，合成后自动拼片）" if corpus_target_clips else "")
            )
            try:
                info = await builder.submit_pipeline(
                    voice_description, texts, target_clips=corpus_target_clips
                )
            except Exception as exc:
                raise _StageError("corpus", f"统一流程任务提交失败: {exc}")
            task_id = info["task_id"]
            run["dataset_id"] = info["dataset_id"]
            ds_name = info["name"]
            run["corpus"]["total"] = info["total"]
        else:
            from modelstation.services import dataset_registry

            self._set_stage(
                run, "reference", "skipped", f"上传模式：使用参考音频 {ref_audio_path}"
            )
            self._set_stage(run, "corpus", "running", "以上传参考音频克隆语料进行中")
            try:
                registered = dataset_registry.register_dataset(
                    engine="pipeline", ref_audio=Path(ref_audio_path).name
                )
            except dataset_registry.DatasetRegistryError as exc:
                raise _StageError("corpus", f"数据集编号分配失败: {exc}")
            run["dataset_id"] = registered["dataset_id"]
            ds_name = registered["name"]
            # 成片模式：按目标条数截断合成文本（2.8×目标，短句拼片后 ≥ 目标）
            synth_texts = list(texts)
            if corpus_target_clips is not None:
                synth_texts = synth_texts[: int(corpus_target_clips * _TEXTS_PER_CLIP)]
            try:
                task_id = await builder.submit(
                    ds_name,
                    synth_texts,
                    engine="cosyvoice3_zero",
                    engine_params={"ref_audio_path": str(ref_audio_path)},
                )
            except Exception as exc:
                raise _StageError("corpus", f"语料生成任务提交失败: {exc}")
            run["corpus"]["total"] = len(synth_texts)

        # 轮询语料任务至终态（failed → run failed）；终态后等待后台任务完全收尾
        # （成片组装在批次生成器落终态之后执行），再读取最终计数
        while True:
            task = builder.get_task(task_id)
            if task is None:
                raise _StageError("corpus", f"语料生成任务不存在: {task_id}")
            run["corpus"]["done"] = task["done"]
            run["corpus"]["total"] = task["total"]
            if task["status"] in ("completed", "failed"):
                await builder.wait_task(task_id)
                task = builder.get_task(task_id) or task
                run["corpus"]["done"] = task["done"]
                run["corpus"]["total"] = task["total"]
                if task["status"] == "failed":
                    if voice_description:
                        # 提示词模式下参考音频生成失败同样归属 reference 阶段
                        self._set_stage(
                            run, "reference", "failed", task.get("error") or "参考音频生成失败"
                        )
                    raise _StageError(
                        "corpus", f"语料生成任务失败: {task.get('error') or '未知错误'}"
                    )
                break
            await asyncio.sleep(_CORPUS_POLL_SECONDS)

        if voice_description:
            self._set_stage(run, "reference", "completed", "初始参考音频已生成（qwen3_voicedesign）")
        if corpus_target_clips is not None and not voice_description:
            # 上传模式成片：语料任务已终态（目录锁已释放），按句子边界组装切片
            try:
                await asyncio.to_thread(
                    assemble_sentence_clips, resolve_dataset_dir(ds_name)
                )
            except Exception as exc:
                logger.warning("上传模式语料成片组装失败（保留逐句切片）: %s", exc)
            count = count_corpus_entries(resolve_dataset_dir(ds_name))
            run["corpus"]["done"] = count
            run["corpus"]["total"] = count
        self._set_stage(
            run,
            "corpus",
            "completed",
            f"数据集 {run['dataset_id']}（{ds_name}）语料生成完成"
            f"（{run['corpus']['done']}/{run['corpus']['total']}）",
        )
        return ds_name

    # ------------------------------------------------------------------
    # 阶段 3：preprocess（按 model_type 分发）
    # ------------------------------------------------------------------

    async def _stage_preprocess(self, run: dict, ds_name: str) -> None:
        self._set_stage(run, "preprocess", "running", "数据预处理进行中")
        if run["model_type"] == MODEL_TYPE_SOVITS:
            from modelstation.api.sovits_svc import get_sovits_trainer
            from modelstation.services.dataset_builder import resolve_datasets_root

            trainer = get_sovits_trainer()
            try:
                results = await trainer.preprocess(
                    training_data_dir=str(resolve_datasets_root().parent),
                    speaker_name=ds_name,
                )
            except Exception as exc:
                raise _StageError("preprocess", f"So-VITS-SVC 预处理失败: {exc}")
            failed = [
                name for name, item in results.items()
                if isinstance(item, dict) and not item.get("success", False)
            ]
            if failed:
                raise _StageError(
                    "preprocess", f"So-VITS-SVC 预处理步骤失败: {', '.join(failed)}"
                )
            self._set_stage(
                run, "preprocess", "completed",
                f"So-VITS-SVC 三步预处理完成（speaker={ds_name}）",
            )
        else:
            from modelstation.services.dataset_builder import resolve_dataset_dir
            from modelstation.services.melotts_dataset_prep import prepare_filelists

            try:
                stats = prepare_filelists(dataset_dir=str(resolve_dataset_dir(ds_name)))
            except Exception as exc:
                raise _StageError("preprocess", f"MeloTTS 数据准备失败: {exc}")
            self._set_stage(
                run, "preprocess", "completed",
                "MeloTTS filelist 准备完成"
                f"（train={stats.get('train_count')} val={stats.get('val_count')}）",
            )

    # ------------------------------------------------------------------
    # 阶段 4：training（互斥 + Loss 判停）
    # ------------------------------------------------------------------

    async def _stage_training(
        self,
        run: dict,
        ds_name: str,
        output_name: Optional[str],
        max_epochs: int,
        n_texts: int,
    ) -> str:
        """训练阶段：输出模型名缺省 auto_<DS编号>_<类型>（覆盖同样过白名单）。"""
        self._set_stage(run, "training", "running", "训练进行中")
        model_name = output_name or f"auto_{run['dataset_id']}_{run['model_type']}"
        if not _OUTPUT_NAME_PATTERN.match(model_name):
            raise _StageError("training", f"Invalid output_name: {model_name!r}")
        run["training"]["total_epochs"] = max_epochs
        if run["model_type"] == MODEL_TYPE_SOVITS:
            return await self._train_sovits(run, ds_name, model_name, max_epochs)
        return await self._train_melotts(run, model_name, max_epochs, n_texts)

    def _sovits_log_path(self, model_name: str) -> Path:
        """sovits 引擎训练日志路径（engines/so-vits-svc-4.1-Stable/logs/<名>/train.log）。"""
        from modelstation.config import get_settings

        return (
            Path(get_settings().sovits_svc.so_vits_svc_dir)
            / "logs" / model_name / "train.log"
        )

    def _melotts_log_path(self, model_name: str) -> Path:
        """melotts 引擎训练日志路径（engines/MeloTTS/melo/logs/<名>/train.log）。"""
        from modelstation.config import get_settings

        return (
            Path(get_settings().melotts.engine_dir)
            / "melo" / "logs" / model_name / "train.log"
        )

    def _maybe_stop_by_loss(
        self, judge: LossJudge, log_path: Path, max_epochs: int
    ) -> Optional[tuple[str, str]]:
        """读取引擎日志判定是否判停；命中 converged/overfit_risk 返回 (status, reason)。

        日志尚未产生（FileNotFoundError）或读取失败时返回 None（继续训练）。
        """
        try:
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        try:
            status, reason = judge.judge_log(log_text, max_epochs)
        except Exception as exc:  # 解析容错：单轮解析失败不影响训练
            logger.warning("Loss 判停日志解析失败（忽略本轮）: %s (%s)", log_path, exc)
            return None
        if status in ("converged", "overfit_risk"):
            logger.info("一键成模 Loss 判停命中: %s (%s)", status, reason)
            return status, reason or status
        return None

    def _final_fitting_status(
        self, judge: LossJudge, log_path: Path, max_epochs: int
    ) -> Optional[tuple[str, Optional[str]]]:
        """自然终态后的拟合状态回填：仅 max_epochs 命中时回填（其余置 None）。

        极短训练可能未达到 log_interval 而无任何损失行（判停器无样本），
        此时按 epoch 标记行兜底：已解析到的最大 epoch >= max_epochs 视为到顶。
        """
        try:
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        try:
            status, reason = judge.judge_log(log_text, max_epochs)
        except Exception:
            status, reason = None, None
        if status == "max_epochs":
            return status, reason
        # 兜底：无损失样本时按 epoch 标记行判断是否到顶
        last_epoch = max(
            (int(m.group(1)) for m in _ANY_EPOCH_MARK_RE.finditer(log_text)), default=0
        )
        if max_epochs > 0 and last_epoch >= max_epochs:
            return "max_epochs", f"已解析到 epoch {last_epoch}，达到本次训练上限（{max_epochs}）"
        return None

    def _write_stop_sentinel(self, log_path: Path) -> None:
        """优雅停止：在模型目录写 .stop_requested 哨兵，引擎下一个 epoch 边界存盘退出。"""
        try:
            sentinel = log_path.parent / _STOP_SENTINEL_NAME
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.write_text("", encoding="utf-8")
            logger.info("已写入优雅停止哨兵: %s", sentinel)
        except OSError as exc:
            logger.warning("写入优雅停止哨兵失败（将走强杀兜底）: %s", exc)

    async def _train_sovits(
        self, run: dict, ds_name: str, model_name: str, max_epochs: int
    ) -> str:
        """sovits 训练：按 api/sovits_svc.py 的模式消费跨类型训练互斥 + Loss 判停。"""
        from modelstation.api import sovits_svc as sovits_svc_api
        from modelstation.services.training_mutex import (
            TRAINING_SOVITS_SVC,
            end_training,
            try_begin_training,
            update_training_task,
        )

        # 跨类型训练互斥（同一时间仅一个训练任务；冲突传导为 run failed，409 语义）
        mutex_ok, mutex_current = try_begin_training(TRAINING_SOVITS_SVC, None)
        if not mutex_ok:
            holder = dict(mutex_current or {})
            raise _StageError(
                "training",
                "训练互斥冲突(409): 训练任务正在进行中"
                f"（类型: {holder.get('owner_type')}, task_id: {holder.get('task_id')}）",
            )

        trainer = sovits_svc_api.get_sovits_trainer()
        terminal: dict = {"status": None, "message": ""}
        terminal_event = asyncio.Event()

        def _progress_cb(**kw) -> None:
            """训练进度回调：更新 run 的 training 进度；终态置事件。"""
            if "progress" in kw:
                run["training"]["progress"] = float(kw["progress"])
            if "epoch" in kw:
                run["training"]["epoch"] = int(kw["epoch"])
            status = kw.get("status")
            if status in ("completed", "failed"):
                terminal["status"] = status
                terminal["message"] = str(kw.get("message") or "")
                terminal_event.set()

        try:
            task_id = await trainer.start_training(
                epochs=max_epochs,
                output_name=model_name,
                speaker_name=ds_name,
                progress_callback=_progress_cb,
                # 检查点节拍（自然到顶路径）：按总步数规划 eval_interval，保证到顶时
                # 检查点新鲜且写盘摊薄（判停路径由 .stop_requested 哨兵优雅存盘）
                eval_interval=_planned_eval_interval(max_epochs, run["corpus"]["total"]),
            )
        except Exception as exc:
            end_training(TRAINING_SOVITS_SVC)  # 启动失败释放互斥（幂等），允许后续重试
            raise _StageError("training", f"So-VITS-SVC 训练启动失败: {exc}")
        update_training_task(TRAINING_SOVITS_SVC, task_id)

        # Loss 判停主循环：命中 converged/overfit_risk → stop_training；
        # epoch>=max_epochs 由引擎自然结束（fitting_status=max_epochs）
        judge = LossJudge(MODEL_TYPE_SOVITS)
        log_path = self._sovits_log_path(model_name)
        stop_info: Optional[tuple[str, str]] = None
        stop_requested = False
        sentinel_deadline = 0.0
        try:
            while not terminal_event.is_set():
                if stop_requested:
                    # 哨兵已写：等引擎下一个 epoch 边界存盘退出；超时未退才强杀兜底
                    if time.monotonic() >= sentinel_deadline:
                        logger.warning("优雅停止超时，强杀训练子进程（产物取最近检查点）")
                        await trainer.stop_training()
                        break
                else:
                    stop_info = self._maybe_stop_by_loss(judge, log_path, max_epochs)
                    if stop_info is not None:
                        stop_requested = True
                        self._write_stop_sentinel(log_path)
                        sentinel_deadline = time.monotonic() + _STOP_FALLBACK_SECONDS
                        continue
                await asyncio.sleep(_TRAIN_POLL_SECONDS)
        finally:
            # 终态（completed/failed/stopped）释放互斥（end_training 幂等）
            end_training(TRAINING_SOVITS_SVC)

        if stop_info is not None:
            run["training"]["fitting_status"], run["training"]["stop_reason"] = stop_info
            self._set_stage(
                run, "training", "completed",
                f"训练已按损失判停（{stop_info[0]}），产物按检查点收集",
            )
        elif terminal["status"] == "failed":
            raise _StageError(
                "training", f"So-VITS-SVC 训练失败: {terminal['message'] or '未知错误'}"
            )
        else:
            fitting = self._final_fitting_status(judge, log_path, max_epochs)
            if fitting is not None:
                run["training"]["fitting_status"], run["training"]["stop_reason"] = fitting
            self._set_stage(
                run, "training", "completed", f"训练完成（epoch={run['training']['epoch']}）"
            )
        return model_name

    async def _train_melotts(
        self, run: dict, model_name: str, max_epochs: int, n_texts: int
    ) -> str:
        """melotts 训练：互斥由 trainer 内部消费；轮询 get_train_status + Loss 判停。

        melotts 无 progress_callback 参数，进度经模块级 get_train_status() 透出。
        """
        from modelstation.services import melotts_trainer as melotts_trainer_module
        from modelstation.services.melotts_trainer import TrainingInProgressError

        trainer = melotts_trainer_module.get_trainer()
        try:
            await trainer.start_training(
                epochs=max_epochs,
                output_name=model_name,
                # batch 走显存自适应（None）；不显式传 batch，否则会吃掉自适应能力
                batch_size=None,
                # 检查点节拍（自然到顶路径）：按总步数规划 eval_interval；判停路径
                # 由 .stop_requested 哨兵优雅存盘（引擎下一个 epoch 边界退出）
                eval_interval=_planned_eval_interval(max_epochs, n_texts),
            )
        except TrainingInProgressError as exc:
            raise _StageError("training", f"训练互斥冲突(409): {exc}")
        except Exception as exc:
            raise _StageError("training", f"MeloTTS 训练启动失败: {exc}")

        judge = LossJudge(MODEL_TYPE_MELOTTS)
        log_path = self._melotts_log_path(model_name)
        stop_info: Optional[tuple[str, str]] = None
        stop_requested = False
        sentinel_deadline = 0.0
        terminal_status = ""
        terminal_message = ""
        while True:
            status = melotts_trainer_module.get_train_status()
            run["training"]["epoch"] = int(status.get("epoch") or 0)
            run["training"]["progress"] = float(status.get("progress") or 0.0)
            terminal_status = str(status.get("status") or "")
            terminal_message = str(status.get("message") or "")
            if terminal_status in ("completed", "failed", "stopped"):
                break
            if stop_requested:
                # 哨兵已写：等引擎下一个 epoch 边界存盘退出；超时未退才强杀兜底
                if time.monotonic() >= sentinel_deadline:
                    logger.warning("优雅停止超时，强杀训练子进程（产物取最近检查点）")
                    await trainer.stop_training()
                    break
            else:
                stop_info = self._maybe_stop_by_loss(judge, log_path, max_epochs)
                if stop_info is not None:
                    stop_requested = True
                    self._write_stop_sentinel(log_path)
                    sentinel_deadline = time.monotonic() + _STOP_FALLBACK_SECONDS
                    continue
            await asyncio.sleep(_TRAIN_POLL_SECONDS)

        if stop_info is not None:
            run["training"]["fitting_status"], run["training"]["stop_reason"] = stop_info
            self._set_stage(
                run, "training", "completed",
                f"训练已按损失判停（{stop_info[0]}），产物按检查点收集",
            )
        elif terminal_status == "failed":
            raise _StageError(
                "training", f"MeloTTS 训练失败: {terminal_message or '未知错误'}"
            )
        else:
            fitting = self._final_fitting_status(judge, log_path, max_epochs)
            if fitting is not None:
                run["training"]["fitting_status"], run["training"]["stop_reason"] = fitting
            self._set_stage(
                run, "training", "completed", f"训练完成（epoch={run['training']['epoch']}）"
            )
        return model_name

    # ------------------------------------------------------------------
    # 阶段 5：collect（产物定位与回填）
    # ------------------------------------------------------------------

    def _stage_collect(self, run: dict, model_name: str) -> None:
        self._set_stage(run, "collect", "running", "模型产物收集中")
        from modelstation.config import get_settings

        settings = get_settings()
        if run["model_type"] == MODEL_TYPE_SOVITS:
            from modelstation.api.sovits_svc import get_sovits_trainer

            models_dir = Path(settings.sovits_svc.models_dir)
            trainer = get_sovits_trainer()
        else:
            from modelstation.services import melotts_trainer as melotts_trainer_module

            models_dir = Path(settings.melotts.models_dir)
            trainer = melotts_trainer_module.get_trainer()

        model_dir = models_dir / model_name
        try:
            has_g = model_dir.is_dir() and any(model_dir.glob("G_*.pth"))
            if not has_g:
                # 判停（stopped）路径 trainer 不收集产物：此处兜底收集
                # （_collect_outputs 仅要求 G 检查点存在，容忍 D/DUR 缺失）
                trainer._collect_outputs(model_name)
        except Exception as exc:
            raise _StageError("collect", f"训练产物收集失败: {exc}")

        files = (
            sorted(f.name for f in model_dir.iterdir() if f.is_file())
            if model_dir.is_dir()
            else []
        )
        if not any(name.startswith("G_") for name in files):
            raise _StageError(
                "collect", f"训练产物缺失（{model_dir} 下无 G_*.pth 检查点）"
            )
        run["result"] = {
            "model_name": model_name,
            "model_dir": str(model_dir),
            "files": files,
        }
        self._set_stage(run, "collect", "completed", f"模型产物已就绪：{model_dir}")


# ---------------------------------------------------------------------------
# 模块级单例（与 dataset_builder / 两 trainer 的单例模式一致）
# ---------------------------------------------------------------------------

_pipeline_instance: Optional[AutoModelPipelineService] = None


def get_auto_model_pipeline() -> AutoModelPipelineService:
    """获取一键成模编排服务稳定单例，供 API 路由复用"""
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = AutoModelPipelineService()
    return _pipeline_instance


def reset_auto_model_pipeline() -> None:
    """重置单例（测试专用）。"""
    global _pipeline_instance
    _pipeline_instance = None
