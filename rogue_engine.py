"""
奇维鸟·星蚀试炼塔 — 路线选择式肉鸽副本引擎
独立模块，被 DDTank_gui.py 在 __main__ 块前 import 并注册路由
"""
import random, json, time, copy
from datetime import date

# ═══ 常量 ═══
ROGUE_MIN_POWER = 2000
ROGUE_MAX_POWER = 120000
ROGUE_FLOORS = 20

def rogue_recommended_power(floor):
    return int(ROGUE_MIN_POWER * (ROGUE_MAX_POWER / ROGUE_MIN_POWER) ** ((floor - 1) / (ROGUE_FLOORS - 1)))

ROOM_MULTIPLIERS = {
    "monster": 1.00, "elite": 1.35, "event": 0.60, "item": 0.00,
    "card": 0.00, "shop": 0.00, "rest": 0.00, "boss": 2.20
}

REWARD_MULTIPLIERS = {
    "monster": 0.65, "elite": 1.45, "event": 0.30, "item": 0.20,
    "card": 0.10, "shop": 0.00, "rest": 0.00, "boss": 5.00
}

NODE_TYPE_ICONS = {
    "monster": "⚔️", "elite": "💀", "event": "❓", "item": "🎁",
    "card": "🃏", "shop": "🏪", "rest": "🔥", "boss": "👑"
}

NODE_TYPE_COLORS = {
    "monster": "#4a90d9", "elite": "#cc44ff", "event": "#ffaa00", "item": "#44cc66",
    "card": "#9966ff", "shop": "#ffcc00", "rest": "#44cccc", "boss": "#cc2222"
}

# ═══ 卡牌池 ═══
ROGUE_CARDS = [
    # 攻击卡
    {"id":"atk_up","name":"火力增幅","type":"attack","quality":"common","desc":"攻击+8%","effect":"atk_pct","value":8},
    {"id":"dmg_up","name":"强袭弹","type":"attack","quality":"common","desc":"普攻伤害+12%","effect":"dmg_pct","value":12},
    {"id":"armor_break","name":"破甲弹","type":"attack","quality":"rare","desc":"无视18%护甲","effect":"ignore_armor","value":18},
    {"id":"double_shot","name":"双重射击","type":"attack","quality":"epic","desc":"每3回合额外攻击70%","effect":"extra_attack_3","value":70},
    {"id":"star_cannon","name":"星陨重炮","type":"attack","quality":"epic","desc":"每4回合伤害+100%","effect":"boost_4","value":100},
    {"id":"judge","name":"奇维鸟审判","type":"attack","quality":"legend","desc":"Boss伤害+35%,暴伤+35%","effect":"boss_crit","value":35},
    {"id":"eclipse_final","name":"星蚀终炮","type":"attack","quality":"mythic","desc":"首击250%,2回合敌受伤+20%","effect":"first_strike","value":250},
    # 属性卡
    {"id":"hp_up","name":"生命强化","type":"stat","quality":"common","desc":"最大生命+12%","effect":"hp_pct","value":12},
    {"id":"luck_up","name":"幸运羽毛","type":"stat","quality":"common","desc":"幸运+12%","effect":"luk_pct","value":12},
    {"id":"focus","name":"战斗专注","type":"stat","quality":"rare","desc":"暴击率+8%","effect":"crit_up","value":8},
    {"id":"extreme_fire","name":"极限火力","type":"stat","quality":"epic","desc":"攻击+25%,受伤+8%","effect":"atk25_dmg8","value":25},
    {"id":"steel_wing","name":"钢铁羽翼","type":"stat","quality":"epic","desc":"HP+22%,护甲+15%","effect":"hp_armor","value":22},
    {"id":"star_core","name":"星核共鸣","type":"stat","quality":"legend","desc":"全属性+15%","effect":"all_up","value":15},
    # 防御卡
    {"id":"shield","name":"厚羽护盾","type":"defense","quality":"common","desc":"开场HP8%护盾","effect":"start_shield","value":8},
    {"id":"heal_end","name":"应急包扎","type":"defense","quality":"common","desc":"战后恢复8%HP","effect":"end_heal","value":8},
    {"id":"unyielding","name":"不屈羽翼","type":"defense","quality":"epic","desc":"HP<30%恢复22%","effect":"low_hp_heal","value":22},
    # 怒气卡
    {"id":"rage_flow","name":"怒气回流","type":"rage","quality":"common","desc":"每回合+8怒气","effect":"rage_per_turn","value":8},
    {"id":"war_spirit","name":"战意高涨","type":"rage","quality":"rare","desc":"开局+35怒气","effect":"start_rage","value":35},
    # 回复卡
    {"id":"regen","name":"轻微恢复","type":"heal","quality":"common","desc":"每回合回1.5%HP","effect":"regen","value":1.5},
    {"id":"life_drain","name":"生命汲取","type":"heal","quality":"rare","desc":"伤害8%转回血","effect":"lifesteal","value":8},
]

CARD_QUALITY_ORDER = {"common": 1, "rare": 2, "epic": 3, "legend": 4, "mythic": 5}

# ═══ 敌人技能 ═══
ROGUE_ENEMY_SKILLS = {
    "normal": [
        {"name":"连续啄击","desc":"连续攻击2次","hits":2,"dmg_pct":55,"min_floor":3},
        {"name":"羽刃投射","desc":"120%伤害,下回合受伤+10%","dmg_pct":120,"debuff":"dmg_taken_up","min_floor":4},
        {"name":"暗羽护体","desc":"获得12%HP护盾","shield_pct":12,"min_floor":5},
        {"name":"生命啄食","desc":"90%伤害,30%吸血","dmg_pct":90,"lifesteal":30,"min_floor":6},
        {"name":"怒气干扰","desc":"80%伤害,减少玩家10怒气","dmg_pct":80,"rage_down":10,"min_floor":7},
    ],
    "elite": [
        {"name":"三连碎羽","desc":"连续攻击3次","hits":3,"dmg_pct":45,"min_floor":10},
        {"name":"星蚀回血","desc":"恢复15%HP","heal_pct":15,"min_floor":10},
        {"name":"破甲尖啸","desc":"100%伤害,降护甲12%","dmg_pct":100,"armor_down":12,"min_floor":12},
        {"name":"反击姿态","desc":"下次攻击后立即反击","counter":True,"min_floor":13},
    ],
    "boss": [
        {"name":"星蚀连击","desc":"连续攻击4次","hits":4,"dmg_pct":40,"min_floor":20},
        {"name":"黑羽再生","desc":"恢复18%HP","heal_pct":18,"min_floor":20},
        {"name":"奇维鸟威压","desc":"降低玩家攻击15%","debuff":"atk_down","atk_down":15,"min_floor":20},
        {"name":"终层护盾","desc":"获得20%HP护盾","shield_pct":20,"min_floor":20},
        {"name":"星核吞噬","desc":"伤害+恢复15%HP","dmg_pct":100,"heal_pct":15,"min_floor":20},
    ],
}

# ═══ 事件池 ═══
ROGUE_EVENTS = [
    {
        "id": "altar","title":"星蚀祭坛","desc":"一座散发暗紫色光芒的祭坛出现在你面前。",
        "choices": [
            {"id":"a","text":"献祭15%生命,获得攻击+12%","effect":"sacrifice_hp_atk","hp_cost_pct":15,"atk_gain":12},
            {"id":"b","text":"献祭3000金币,获得1张稀有卡","effect":"sacrifice_gold_card","gold_cost":3000,"card_quality":"rare"},
            {"id":"c","text":"离开,无事发生","effect":"none"},
        ]
    },
    {
        "id": "broken_jar","title":"破碎魔罐","desc":"地上躺着一个开裂的天使魔罐，隐约透出光芒。",
        "choices": [
            {"id":"a","text":"打开它 (50%奖励,50%受伤)","effect":"gamble","win_chance":50,"win":{"gold":1500,"exp":300},"lose":{"hp_loss_pct":20}},
            {"id":"b","text":"花费5星蚀徽章安全开启","effect":"safe_open","cost_tokens":5,"reward":{"gold":1500,"exp":300}},
            {"id":"c","text":"跳过","effect":"none"},
        ]
    },
    {
        "id": "merchant","title":"黑羽商人","desc":"一个身披黑羽斗篷的神秘商人拦住了你的去路。",
        "choices": [
            {"id":"a","text":"花费2000金币购买攻击药剂","effect":"buy_potion","gold_cost":2000,"item":"atk_potion"},
            {"id":"b","text":"花费3星蚀徽章刷新卡牌","effect":"refresh_cards","cost_tokens":3},
            {"id":"c","text":"离开","effect":"none"},
        ]
    },
    {
        "id": "lost_kiwi","title":"迷失奇维鸟","desc":"一只瑟瑟发抖的小奇维鸟在角落里蜷缩着。",
        "choices": [
            {"id":"a","text":"帮助它,获得随机道具","effect":"help","reward":"random_item"},
            {"id":"b","text":"抢夺它,获得金币但受伤","effect":"rob","gold":2000,"hp_loss_pct":15},
            {"id":"c","text":"放它离开,获得少量经验","effect":"release","exp":200},
        ]
    },
    {
        "id": "rift","title":"星蚀裂隙","desc":"空间撕裂出一道紫色裂隙，能量波动剧烈。",
        "choices": [
            {"id":"a","text":"进入裂隙,下场战斗奖励翻倍但敌人+30%","effect":"enter_rift","next_battle_bonus":2,"enemy_buff":30},
            {"id":"b","text":"吸收能量,恢复20%HP","effect":"heal","heal_pct":20},
            {"id":"c","text":"关闭裂隙,获得2星蚀徽章","effect":"close","tokens":2},
        ]
    },
]

# ═══ 临时道具 ═══
TEMP_ITEMS = [
    {"id":"heal_potion","name":"星蚀药剂","desc":"恢复30%最大HP","effect":"heal","value":30},
    {"id":"armor_break_potion","name":"破甲药剂","desc":"下场战斗无视25%护甲","effect":"ignore_armor_next","value":25},
    {"id":"combo_feather","name":"连击羽毛","desc":"下场战斗首攻追加60%伤害","effect":"first_combo","value":60},
    {"id":"shield_core","name":"防护核心","desc":"下场战斗获得25%HP护盾","effect":"shield_next","value":25},
    {"id":"revive_feather","name":"复苏羽毛","desc":"本次试炼致命伤害时复活一次,恢复30%HP","effect":"revive","value":30},
]

# ═══ 商店商品 ═══
SHOP_ITEMS = [
    {"id":"shop_heal","name":"治疗","desc":"恢复35%最大HP","cost_type":"tokens","cost":2,"effect":"heal","value":35},
    {"id":"shop_card","name":"随机稀有卡","desc":"获得一张稀有品质卡牌","cost_type":"tokens","cost":3,"effect":"random_card","quality":"rare"},
    {"id":"shop_atk","name":"攻击药剂","desc":"下场攻击+20%","cost_type":"tokens","cost":2,"effect":"atk_up_next","value":20},
    {"id":"shop_def","name":"防御药剂","desc":"下场受伤害-20%","cost_type":"tokens","cost":2,"effect":"def_up_next","value":20},
    {"id":"shop_frag","name":"星蚀碎片","desc":"少量永久材料","cost_type":"gold","cost":5000,"effect":"material","value":5},
]

# ═══ 地图生成 ═══
def generate_rogue_map():
    map_nodes = []
    for floor in range(1, ROGUE_FLOORS + 1):
        if floor == 1:
            node_count = 1
            types = ["monster"]
        elif floor == ROGUE_FLOORS:
            node_count = 1
            types = ["boss"]
        elif floor in (5, 10, 15):
            node_count = random.randint(2, 4)
            types_pool = []
            # 必有一个 elite
            types_pool.append("elite")
            # 其他节点
            extra = random.choices(["monster","event","rest","shop"], k=node_count - 1)
            types_pool.extend(extra)
            types = types_pool[:node_count]
        else:
            node_count = random.randint(2, 4)
            if floor <= 4:
                probs = [("monster",60),("event",15),("card",15),("item",10)]
            elif floor <= 9:
                probs = [("monster",45),("elite",15),("event",15),("card",15),("item",10)]
            elif floor <= 14:
                probs = [("monster",40),("elite",20),("event",15),("card",10),("shop",10),("rest",5)]
            else:
                probs = [("monster",35),("elite",25),("event",15),("shop",10),("rest",10),("card",5)]
            type_names, weights = zip(*probs)
            types = list(random.choices(type_names, weights=weights, k=node_count))
        
        rec_power = rogue_recommended_power(floor)
        for i, t in enumerate(types):
            titles = {
                "monster": ["星蚀幼鸟群","暗羽巡游者","裂空啄击者","深渊翼卫"],
                "elite": ["星核守护者","暗翼统领","蚀渊巨喙"],
                "event": ["星蚀祭坛","破碎魔罐","迷失奇维鸟","星蚀裂隙"],
                "item": ["星核补给箱","遗失的军械库","能量结晶"],
                "card": ["记忆回廊","战术复盘室","星能共鸣台"],
                "shop": ["黑羽交易所","裂隙商栈"],
                "rest": ["星辉营地","暖羽休憩所"],
                "boss": ["终焉星蚀奇维鸟王"],
            }
            title = random.choice(titles.get(t, [f"{t}房"]))
            node = {
                "id": f"floor_{floor}_node_{i}",
                "floor": floor,
                "type": t,
                "icon": NODE_TYPE_ICONS.get(t, "?"),
                "title": title,
                "desc": "",
                "recommended_power": rec_power,
                "next": [],
                "completed": False,
                "sprite": "/picture/enemy/default.gif",  # kiwi GIF
                "hue": random.randint(0, 359),  # 随机色相
                "variant": "final_boss" if t == "boss" and floor == ROGUE_FLOORS else ("boss" if t == "boss" else ("elite" if t == "elite" else "normal")),
            }
            map_nodes.append(node)
    
    # 建立连接
    for floor in range(1, ROGUE_FLOORS):
        this_nodes = [n for n in map_nodes if n["floor"] == floor]
        next_nodes = [n for n in map_nodes if n["floor"] == floor + 1]
        for tn in this_nodes:
            num_next = min(len(next_nodes), random.randint(1, 2))
            target_ids = [nn["id"] for nn in random.sample(next_nodes, num_next)]
            tn["next"] = target_ids
    return map_nodes

# ═══ 帮助函数 ═══
def roll_rogue_cards(floor, count=3, min_quality=None):
    pool = [c for c in ROGUE_CARDS if c["quality"] != "mythic" and c["quality"] != "legend"]
    if min_quality:
        min_q = CARD_QUALITY_ORDER.get(min_quality, 1)
        pool = [c for c in ROGUE_CARDS if CARD_QUALITY_ORDER.get(c["quality"], 1) >= min_q]
    if floor >= 15 and random.random() < 0.08:
        mythics = [c for c in ROGUE_CARDS if c["quality"] == "mythic"]
        pool += mythics
    if floor >= 10 and random.random() < 0.15:
        legends = [c for c in ROGUE_CARDS if c["quality"] == "legend"]
        pool += legends
    return random.sample(pool, min(count, len(pool)))

def calc_reward(player_power, room_type, floor):
    base_exp = max(50, int(player_power * 0.02))
    base_gold = max(80, int(player_power * 0.03))
    floor_bonus = 0.75 + floor * 0.06
    rm = REWARD_MULTIPLIERS.get(room_type, 0.65)
    room_exp = int(base_exp * rm * floor_bonus)
    room_gold = int(base_gold * rm * floor_bonus)
    return room_gold, room_exp

# ═══ 注册路由 ═══
def register_rogue_routes(app, _save_p_fn, _player_ref, _pd_fn, _jsonify, _request, _random, _threading):
    """注册所有试炼塔路由 — _player_ref 是可变容器，如 [player_obj]"""
    from flask import jsonify as fj, request as fr
    
    def get_player():
        # 通过可变引用获取当前player，避免循环import问题
        if hasattr(_player_ref, 'v'):
            return _player_ref.v
        return None  # fallback
    
    def pd_wrapper():
        import DDTank_gui
        try:
            return DDTank_gui.pd()
        except Exception as e:
            print(f"[Rogue] pd() failed: {e}")
            p = get_player()
            if not p: return {}
            return {"name":p.name,"level":p.level,"coins":p.coins,"power":0,"maxhp":p.maxhp}
    
    def save_wrapper():
        try:
            import DDTank_gui
            DDTank_gui.save_p()
        except Exception as e:
            print(f"[Rogue] Save failed: {e}")
    
    @app.route('/api/rogue/info', methods=['GET','POST'])
    @app.route('/api/rogue/state', methods=['GET','POST'])
    def api_rogue_info():
        p = get_player()
        if not p: return fj({"ok":False,"error":"未登录"})
        rr = p.stats.get("rogue_run") if hasattr(p,'stats') else None
        cp = p.power
        can_enter = cp >= ROGUE_MIN_POWER
        
        # 每日次数
        today = date.today().isoformat()
        rd = p.stats.get("rogue_daily", {})
        if rd.get("date") != today:
            rd = {"date": today, "free_used": 0, "key_used": 0}
            p.stats["rogue_daily"] = rd
        free_remaining = max(0, 1 - rd.get("free_used", 0))
        keys = p.stats.get("rogue_keys", 0)
        
        # 如果没活跃run但免费次数用了且没钥匙,不能进
        if not (rr and rr.get("active")):
            if free_remaining <= 0 and keys <= 0:
                can_enter = False
        
        return fj({"ok":True,"can_enter":can_enter,"min_power":ROGUE_MIN_POWER,
            "player_power":cp,"rogue_run":rr,"floor_count":ROGUE_FLOORS,
            "free_remaining":free_remaining,"keys":keys})
    
    @app.route('/api/rogue/start', methods=['POST'])
    def api_rogue_start():
        p = get_player()
        if not p: return fj({"ok":False,"error":"未登录"})
        try:
            cp = p.power
        except Exception as e:
            import traceback
            traceback.print_exc()
            return fj({"ok":False,"error":f"power计算失败: {e}"})
        if cp < ROGUE_MIN_POWER:
            return fj({"ok":False,"error":f"你的战斗力不足，星蚀试炼塔最低需要{ROGUE_MIN_POWER}战斗力"})
        
        # 每日限制
        today = date.today().isoformat()
        rd = p.stats.get("rogue_daily", {})
        if rd.get("date") != today:
            rd = {"date": today, "free_used": 0, "key_used": 0}
        
        use_key = False
        if rd.get("free_used", 0) >= 1:
            keys = p.stats.get("rogue_keys", 0)
            if keys > 0:
                p.stats["rogue_keys"] = keys - 1
                rd["key_used"] = rd.get("key_used", 0) + 1
                use_key = True
            else:
                return fj({"ok":False,"error":"今日免费次数已用完，且没有星蚀钥匙。钥匙可通过副本/魔罐获得"})
        else:
            rd["free_used"] = rd.get("free_used", 0) + 1
        
        p.stats["rogue_daily"] = rd
        
        # 生成地图
        rmap = generate_rogue_map()
        start_node = next(n for n in rmap if n["floor"] == 1)
        rr = {
            "active": True,
            "map": rmap,
            "current_floor": 1,
            "current_node_id": None,
            "available_node_ids": [start_node["id"]],
            "completed_node_ids": [],
            "selected_cards": [],
            "upgraded_cards": [],
            "temporary_buffs": {},
            "temp_items": [],
            "current_hp": p.maxhp,
            "current_shield": 0,
            "current_enemy": None,
            "accumulated_rewards": {"gold": 0, "exp": 0},
            "event_choices_made": {},
            "shop_purchases": {},
            "warning_shown_floor20": False,
            "used_key": use_key,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        p.stats["rogue_run"] = rr
        p.stats["rogue_attempts"] = p.stats.get("rogue_attempts", 0) + 1
        save_wrapper()
        return fj({"ok":True,"rogue_run":rr,"player":pd_wrapper()})
    
    @app.route('/api/rogue/enter_node', methods=['POST'])
    def api_rogue_enter_node():
        p = get_player()
        if not p: return fj({"ok":False,"error":"未登录"})
        d = fr.get_json(force=True,silent=True) or {}
        node_id = d.get("node_id", "")
        rr = p.stats.get("rogue_run")
        if not rr or not rr.get("active"):
            return fj({"ok":False,"error":"无活跃试炼"})
        if node_id not in rr.get("available_node_ids", []):
            return fj({"ok":False,"error":"当前路线无法到达此房间"})
        
        node = next((n for n in rr["map"] if n["id"] == node_id), None)
        if not node:
            return fj({"ok":False,"error":"房间不存在"})
        
        # 战斗力警告
        rec_power = node.get("recommended_power", 0)
        
        rr["current_node_id"] = node_id
        rr["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        p.stats["rogue_run"] = rr
        save_wrapper()
        
        room_type = node["type"]
        result = {"ok": True, "node": node, "room_type": room_type,
                  "player_power": p.power, "recommended_power": rec_power,
                  "under_powered": p.power < rec_power}
        
        if room_type in ("monster", "elite", "boss"):
            result["battle_ready"] = True
            result["enemy_name"] = node["title"]
            result["enemy_type"] = room_type
            result["enemy_sprite"] = node.get("sprite", "/picture/enemy/default.gif")
            result["enemy_hue"] = node.get("hue", 0)
            result["enemy_variant"] = node.get("variant", "normal")
        elif room_type == "event":
            evt = random.choice(ROGUE_EVENTS)
            if node_id in rr.get("event_choices_made", {}):
                result["already_used"] = True
            else:
                result["event"] = evt
        elif room_type == "item":
            item = random.choice(TEMP_ITEMS)
            result["item"] = item
        elif room_type == "card":
            min_q = None
            if rr["current_floor"] >= 15: min_q = "epic"
            elif rr["current_floor"] >= 10: min_q = "rare"
            cards = roll_rogue_cards(rr["current_floor"], 3, min_q)
            result["cards"] = cards
        elif room_type == "shop":
            items = random.sample(SHOP_ITEMS, min(4, len(SHOP_ITEMS)))
            result["shop_items"] = items
            result["player_tokens"] = rr.get("tokens", 0)
        elif room_type == "rest":
            result["rest_options"] = [
                {"id":"heal","text":"恢复35%最大HP","effect":"heal","value":35},
                {"id":"upgrade","text":"强化一张已选卡牌","effect":"upgrade_card","available":len(rr.get("selected_cards",[]))>0},
                {"id":"cleanse","text":"清除负面状态","effect":"cleanse"},
            ]
        
        return fj(result)
    
    @app.route('/api/rogue/battle', methods=['POST'])
    def api_rogue_battle():
        p = get_player()
        if not p: return fj({"ok":False,"error":"未登录"})
        rr = p.stats.get("rogue_run")
        if not rr or not rr.get("active"):
            return fj({"ok":False,"error":"无活跃试炼"})
        
        node_id = rr.get("current_node_id")
        node = next((n for n in rr["map"] if n["id"] == node_id), None)
        if not node:
            return fj({"ok":False,"error":"请先选择房间"})
        
        floor = node["floor"]
        room_type = node["type"]
        
        if room_type not in ("monster", "elite", "boss"):
            return fj({"ok":False,"error":"当前房间不是战斗房"})
        
        # 跳过已完成节点
        if node.get("completed"):
            # 直接推进
            return advance_after_room(p, rr, node)
        
        rm = ROOM_MULTIPLIERS.get(room_type, 1.0)
        rec_power = node["recommended_power"]
        ep = int(rec_power * rm * random.uniform(0.85, 1.15))
        
        # 临时buff: 裂隙效果
        buffs = rr.get("temporary_buffs", {})
        if buffs.get("rift_active"):
            ep = int(ep * 1.3)
        
        ratio = p.power / max(1, ep)
        win_chance = min(0.95, max(0.1, 0.5 + (ratio - 1) * 0.3))
        
        # 道具效果
        temp_items = rr.get("temp_items", [])
        has_revive = any(ti.get("id") == "revive_feather" for ti in temp_items)
        
        won = random.random() < win_chance
        
        if not won and has_revive:
            won = True
            rr["temp_items"] = [ti for ti in temp_items if ti.get("id") != "revive_feather"]
            revive_msg = "🪶 复苏羽毛生效！你从死亡边缘回来了！"
        else:
            revive_msg = None
        
        dmg_taken = int(p.maxhp * random.uniform(0.15, 0.5) * (2 - min(1.5, ratio)))
        dmg_dealt = int(ep * 0.3 * random.uniform(0.8, 1.2) * ratio)
        
        # 选卡效果
        for c in rr.get("selected_cards", []):
            if c["id"] == "start_shield":
                rr["current_shield"] = int(p.maxhp * c["value"] / 100)
            if c["id"] == "dmg_pct" and won:
                dmg_dealt = int(dmg_dealt * (1 + c["value"] / 100))
        
        rr["current_hp"] = max(0, p.maxhp - dmg_taken)
        
        # 敌人技能
        skill_used = None
        skill_chance = 0.5 if room_type == "elite" else (0.8 if room_type == "boss" else 0.2)
        if random.random() < skill_chance:
            skill_pool = ROGUE_ENEMY_SKILLS.get(room_type if room_type == "boss" else ("elite" if room_type == "elite" else "normal"), [])
            skill_pool = [s for s in skill_pool if s.get("min_floor", 0) <= floor]
            if skill_pool:
                skill_used = random.choice(skill_pool)
        
        # 奖励
        rift_bonus = 2 if buffs.get("rift_active") else 1
        gold, exp = calc_reward(p.power, room_type, floor)
        gold *= rift_bonus; exp *= rift_bonus
        
        rr["accumulated_rewards"]["gold"] = rr["accumulated_rewards"].get("gold", 0) + gold
        rr["accumulated_rewards"]["exp"] = rr["accumulated_rewards"].get("exp", 0) + exp
        
        # 清除裂隙buff
        if buffs.get("rift_active"):
            buffs["rift_active"] = False
            rr["temporary_buffs"] = buffs
        
        if won:
            p.coins += gold
            p.gain_exp(exp)
            node["completed"] = True
            rr["completed_node_ids"] = rr.get("completed_node_ids", []) + [node_id]
            
            # 精英怪奖励额外选卡
            cards = None
            if room_type in ("elite",):
                min_q = "rare" if floor >= 15 else None
                cards = roll_rogue_cards(floor, 3, min_q)
            elif room_type == "monster":
                if random.random() < 0.3:
                    cards = roll_rogue_cards(floor, 3)
            
            # Boss特殊
            if room_type == "boss":
                p.stats["rogue_boss_kills"] = p.stats.get("rogue_boss_kills", 0) + 1
                p.stats["rogue_floor20_attempts"] = p.stats.get("rogue_floor20_attempts", 0) + 1
                p.stats["rogue_clears"] = p.stats.get("rogue_clears", 0) + 1
                p.stats["rogue_floor20_clears"] = p.stats.get("rogue_floor20_clears", 0) + 1
                rr["active"] = False
                rr["cleared"] = True
                cards = None
            
            # 精英怪统计
            if room_type == "elite":
                p.stats["rogue_elite_kills"] = p.stats.get("rogue_elite_kills", 0) + 1
            
            p.stats["rogue_best_floor"] = max(p.stats.get("rogue_best_floor", 0), floor)
            
            # 推进: 设置下一层可选节点
            result = advance_after_room(p, rr, node)
        else:
            rr["active"] = False
            p.stats["rogue_best_floor"] = max(p.stats.get("rogue_best_floor", 0), floor)
            cards = None
            result = {"ok": True, "won": False, "floor": floor, "node": node,
                      "cards": None, "rogue_run": rr, "skill_used": skill_used,
                      "dmg_taken": dmg_taken, "dmg_dealt": dmg_dealt,
                      "gold": gold, "exp": exp, "player": pd_wrapper(),
                      "enemy_sprite": node.get("sprite",""), "enemy_hue": node.get("hue",0),
                      "enemy_variant": node.get("variant","normal")}
        
        p.stats["rogue_run"] = rr
        save_wrapper()
        
        if result.get("won") and cards:
            result["cards"] = cards
        if revive_msg:
            result["revive_msg"] = revive_msg
        
        return fj(result)
    
    def advance_after_room(p, rr, node):
        """完成房间后推进到下一层"""
        floor = node["floor"]
        next_ids = node.get("next", [])
        
        if floor >= ROGUE_FLOORS or not next_ids:
            # 通关或到达终点
            if node.get("type") == "boss":
                rr["active"] = False
                rr["cleared"] = True
            return {"ok": True, "won": True, "floor": floor, "node": node,
                    "cards": None, "rogue_run": rr, "cleared": rr.get("cleared", False),
                    "skill_used": None, "dmg_taken": 0, "dmg_dealt": 0,
                    "gold": 0, "exp": 0, "player": pd_wrapper(),
                    "available_node_ids": [],
                    "message": "🏆 恭喜通关星蚀试炼塔！" if rr.get("cleared") else "到达终点"}
        
        rr["available_node_ids"] = next_ids
        rr["current_floor"] = node["floor"] + 1
        rr["current_node_id"] = None
        
        return {"ok": True, "won": True, "floor": floor, "node": node,
                "cards": None, "rogue_run": rr, "cleared": False,
                "skill_used": None, "dmg_taken": 0, "dmg_dealt": 0,
                "gold": 0, "exp": 0, "player": pd_wrapper(),
                "enemy_sprite": node.get("sprite",""), "enemy_hue": node.get("hue",0),
                "enemy_variant": node.get("variant","normal"),
                "available_node_ids": next_ids}
    
    @app.route('/api/rogue/pick_card', methods=['POST'])
    def api_rogue_pick_card():
        p = get_player()
        d = fr.get_json(force=True,silent=True) or {}
        card_id = d.get("card_id", "")
        rr = p.stats.get("rogue_run")
        if not rr: return fj({"ok":False,"error":"无活跃试炼"})
        card = next((c for c in ROGUE_CARDS if c["id"] == card_id), None)
        if card:
            rr["selected_cards"] = rr.get("selected_cards", []) + [card]
            p.stats["rogue_cards_picked"] = p.stats.get("rogue_cards_picked", 0) + 1
            if card["quality"] == "mythic":
                p.stats["rogue_mythic_rewards"] = p.stats.get("rogue_mythic_rewards", 0) + 1
        p.stats["rogue_run"] = rr
        save_wrapper()
        return fj({"ok":True,"rogue_run":rr,"player":pd_wrapper()})
    
    @app.route('/api/rogue/event_choice', methods=['POST'])
    def api_rogue_event_choice():
        p = get_player()
        d = fr.get_json(force=True,silent=True) or {}
        event_id = d.get("event_id", "")
        choice_id = d.get("choice_id", "")
        rr = p.stats.get("rogue_run")
        if not rr: return fj({"ok":False,"error":"无活跃试炼"})
        
        node_id = rr.get("current_node_id")
        if not node_id: return fj({"ok":False,"error":"请先进入房间"})
        
        # 防重复
        if node_id in rr.get("event_choices_made", {}):
            return fj({"ok":False,"error":"此事件已经选择过了"})
        
        evt = next((e for e in ROGUE_EVENTS if e["id"] == event_id), None)
        if not evt: return fj({"ok":False,"error":"事件不存在"})
        choice = next((c for c in evt["choices"] if c["id"] == choice_id), None)
        if not choice: return fj({"ok":False,"error":"选项不存在"})
        
        result_msg = ""
        effect = choice.get("effect", "")
        
        if effect == "sacrifice_hp_atk":
            hp_lost = int(p.maxhp * choice["hp_cost_pct"] / 100)
            rr["current_hp"] = max(1, rr.get("current_hp", p.maxhp) - hp_lost)
            rr["temporary_buffs"]["atk_bonus"] = rr["temporary_buffs"].get("atk_bonus", 0) + choice["atk_gain"]
            result_msg = f"献祭{hp_lost}HP,攻击永久+{choice['atk_gain']}%"
        elif effect == "sacrifice_gold_card":
            if p.coins >= choice["gold_cost"]:
                p.coins -= choice["gold_cost"]
                card = roll_rogue_cards(rr["current_floor"], 1, choice["card_quality"])[0]
                rr["selected_cards"] = rr.get("selected_cards", []) + [card]
                result_msg = f"花费{choice['gold_cost']}金币,获得卡牌:{card['name']}"
            else:
                result_msg = "金币不足"
        elif effect == "gamble":
            if random.randint(1, 100) <= choice["win_chance"]:
                win = choice["win"]
                p.coins += win["gold"]
                p.gain_exp(win["exp"])
                result_msg = f"🎉 获得{win['gold']}金币+{win['exp']}经验"
            else:
                hp_lost = int(p.maxhp * choice["lose"]["hp_loss_pct"] / 100)
                rr["current_hp"] = max(1, rr.get("current_hp", p.maxhp) - hp_lost)
                result_msg = f"💥 受伤,损失{hp_lost}HP"
        elif effect == "safe_open":
            tokens = rr.get("tokens", 0)
            if tokens >= choice["cost_tokens"]:
                rr["tokens"] = tokens - choice["cost_tokens"]
                reward = choice["reward"]
                p.coins += reward["gold"]
                p.gain_exp(reward["exp"])
                result_msg = f"安全开启!获得{reward['gold']}金币+{reward['exp']}经验"
            else:
                result_msg = "星蚀徽章不足"
        elif effect == "buy_potion":
            if p.coins >= choice["gold_cost"]:
                p.coins -= choice["gold_cost"]
                rr["temp_items"] = rr.get("temp_items", []) + [{"id":"atk_potion","name":"攻击药剂","desc":"下场战斗攻击+20%","effect":"atk_up_next","value":20}]
                result_msg = "购买了攻击药剂"
            else:
                result_msg = "金币不足"
        elif effect == "refresh_cards":
            tokens = rr.get("tokens", 0)
            if tokens >= choice["cost_tokens"]:
                rr["tokens"] = tokens - choice["cost_tokens"]
                result_msg = "卡牌已刷新(下次选卡品质提升)"
                rr["temporary_buffs"]["card_boost"] = True
            else:
                result_msg = "星蚀徽章不足"
        elif effect == "help":
            item = random.choice(TEMP_ITEMS)
            rr["temp_items"] = rr.get("temp_items", []) + [item]
            result_msg = f"获得道具:{item['name']}"
        elif effect == "rob":
            p.coins += choice["gold"]
            hp_lost = int(p.maxhp * choice["hp_loss_pct"] / 100)
            rr["current_hp"] = max(1, rr.get("current_hp", p.maxhp) - hp_lost)
            result_msg = f"抢夺{choice['gold']}金币,但受伤损失{hp_lost}HP"
        elif effect == "release":
            p.gain_exp(choice["exp"])
            result_msg = f"获得{choice['exp']}经验"
        elif effect == "enter_rift":
            rr["temporary_buffs"]["rift_active"] = True
            result_msg = "进入裂隙!下场战斗奖励翻倍但敌人增强"
        elif effect == "heal":
            heal_amt = int(p.maxhp * choice["heal_pct"] / 100)
            rr["current_hp"] = min(p.maxhp, rr.get("current_hp", p.maxhp) + heal_amt)
            result_msg = f"恢复{heal_amt}HP"
        elif effect == "close":
            rr["tokens"] = rr.get("tokens", 0) + choice["tokens"]
            result_msg = f"获得{choice['tokens']}星蚀徽章"
        else:
            result_msg = "无事发生"
        
        rr["event_choices_made"] = rr.get("event_choices_made", {})
        rr["event_choices_made"][node_id] = choice_id
        p.stats["rogue_events_completed"] = p.stats.get("rogue_events_completed", 0) + 1
        p.stats["rogue_run"] = rr
        save_wrapper()
        
        # 标记节点完成并推进
        node = next((n for n in rr["map"] if n["id"] == node_id), None)
        if node: node["completed"] = True
        rr["completed_node_ids"] = rr.get("completed_node_ids", []) + [node_id]
        
        advance_result = advance_after_room(p, rr, node) if node else {}
        advance_result["event_result"] = result_msg
        return fj(advance_result)
    
    @app.route('/api/rogue/item_claim', methods=['POST'])
    def api_rogue_item_claim():
        p = get_player()
        d = fr.get_json(force=True,silent=True) or {}
        item_id = d.get("item_id", "")
        rr = p.stats.get("rogue_run")
        if not rr: return fj({"ok":False,"error":"无活跃试炼"})
        node_id = rr.get("current_node_id")
        if node_id in rr.get("completed_node_ids", []):
            return fj({"ok":False,"error":"已经领取过此道具"})
        item = next((it for it in TEMP_ITEMS if it["id"] == item_id), None)
        if not item:
            return fj({"ok":False,"error":"道具不存在"})
        rr["temp_items"] = rr.get("temp_items", []) + [item]
        node = next((n for n in rr["map"] if n["id"] == node_id), None)
        if node: node["completed"] = True
        rr["completed_node_ids"] = rr.get("completed_node_ids", []) + [node_id]
        p.stats["rogue_run"] = rr
        save_wrapper()
        
        result = advance_after_room(p, rr, node) if node else {}
        result["item_received"] = item["name"]
        return fj(result)
    
    @app.route('/api/rogue/shop_buy', methods=['POST'])
    def api_rogue_shop_buy():
        p = get_player()
        d = fr.get_json(force=True,silent=True) or {}
        item_id = d.get("item_id", "")
        rr = p.stats.get("rogue_run")
        if not rr: return fj({"ok":False,"error":"无活跃试炼"})
        node_id = rr.get("current_node_id")
        
        shop_item = next((si for si in SHOP_ITEMS if si["id"] == item_id), None)
        if not shop_item:
            return fj({"ok":False,"error":"商品不存在"})
        
        purchases = rr.get("shop_purchases", {})
        if node_id in purchases and item_id in purchases.get(node_id, []):
            return fj({"ok":False,"error":"已经购买过此商品"})
        
        cost_type = shop_item["cost_type"]
        cost = shop_item["cost"]
        if cost_type == "tokens":
            if rr.get("tokens", 0) < cost:
                return fj({"ok":False,"error":"星蚀徽章不足"})
            rr["tokens"] = rr.get("tokens", 0) - cost
        else:
            if p.coins < cost:
                return fj({"ok":False,"error":"金币不足"})
            p.coins -= cost
        
        result_msg = ""
        if shop_item["effect"] == "heal":
            heal_amt = int(p.maxhp * shop_item["value"] / 100)
            rr["current_hp"] = min(p.maxhp, rr.get("current_hp", p.maxhp) + heal_amt)
            result_msg = f"恢复{heal_amt}HP"
        elif shop_item["effect"] == "random_card":
            card = roll_rogue_cards(rr["current_floor"], 1, shop_item["quality"])[0]
            rr["selected_cards"] = rr.get("selected_cards", []) + [card]
            result_msg = f"获得卡牌:{card['name']}"
        elif shop_item["effect"] == "atk_up_next":
            rr["temporary_buffs"]["shop_atk_up"] = True
            result_msg = "下场攻击+20%"
        elif shop_item["effect"] == "def_up_next":
            rr["temporary_buffs"]["shop_def_up"] = True
            result_msg = "下场受伤害-20%"
        elif shop_item["effect"] == "material":
            result_msg = f"获得{shop_item['value']}星蚀碎片"
        
        rr["shop_purchases"] = rr.get("shop_purchases", {})
        if node_id not in rr["shop_purchases"]:
            rr["shop_purchases"][node_id] = []
        rr["shop_purchases"][node_id].append(item_id)
        p.stats["rogue_shops_visited"] = p.stats.get("rogue_shops_visited", 0) + 1
        p.stats["rogue_run"] = rr
        save_wrapper()
        return fj({"ok":True,"result":result_msg,"rogue_run":rr,"player":pd_wrapper()})
    
    @app.route('/api/rogue/shop_leave', methods=['POST'])
    def api_rogue_shop_leave():
        p = get_player()
        rr = p.stats.get("rogue_run")
        if not rr: return fj({"ok":False,"error":"无活跃试炼"})
        node_id = rr.get("current_node_id")
        node = next((n for n in rr["map"] if n["id"] == node_id), None)
        if node: node["completed"] = True
        rr["completed_node_ids"] = rr.get("completed_node_ids", []) + [node_id]
        p.stats["rogue_run"] = rr
        save_wrapper()
        result = advance_after_room(p, rr, node) if node else {}
        return fj(result)
    
    @app.route('/api/rogue/rest', methods=['POST'])
    def api_rogue_rest():
        p = get_player()
        d = fr.get_json(force=True,silent=True) or {}
        action = d.get("action", "")
        card_id = d.get("card_id", "")
        rr = p.stats.get("rogue_run")
        if not rr: return fj({"ok":False,"error":"无活跃试炼"})
        node_id = rr.get("current_node_id")
        if node_id in rr.get("completed_node_ids", []):
            return fj({"ok":False,"error":"已经使用过休息房"})
        
        result_msg = ""
        if action == "heal":
            heal_amt = int(p.maxhp * 0.35)
            rr["current_hp"] = min(p.maxhp, rr.get("current_hp", p.maxhp) + heal_amt)
            result_msg = f"恢复{heal_amt}HP"
        elif action == "upgrade":
            if not card_id or not rr.get("selected_cards"):
                return fj({"ok":False,"error":"无可强化卡牌"})
            for c in rr["selected_cards"]:
                if c["id"] == card_id and card_id not in rr.get("upgraded_cards", []):
                    c["value"] = int(c["value"] * 1.5)
                    rr["upgraded_cards"] = rr.get("upgraded_cards", []) + [card_id]
                    result_msg = f"强化了{c['name']}"
                    break
        elif action == "cleanse":
            rr["temporary_buffs"] = {}
            result_msg = "清除了所有负面状态"
        else:
            return fj({"ok":False,"error":"无效操作"})
        
        node = next((n for n in rr["map"] if n["id"] == node_id), None)
        if node: node["completed"] = True
        rr["completed_node_ids"] = rr.get("completed_node_ids", []) + [node_id]
        p.stats["rogue_rests_used"] = p.stats.get("rogue_rests_used", 0) + 1
        p.stats["rogue_run"] = rr
        save_wrapper()
        
        result = advance_after_room(p, rr, node) if node else {}
        result["rest_result"] = result_msg
        return fj(result)
    
    @app.route('/api/rogue/retire', methods=['POST'])
    def api_rogue_retire():
        p = get_player()
        rr = p.stats.get("rogue_run")
        if rr:
            rr["active"] = False
            rr["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            p.stats["rogue_run"] = rr
        save_wrapper()
        return fj({"ok":True,"rogue_run":rr,"player":pd_wrapper()})
    
    @app.route('/api/rogue/boss_warning', methods=['POST'])
    def api_rogue_boss_warning():
        p = get_player()
        rr = p.stats.get("rogue_run")
        if not rr: return fj({"ok":False,"error":"无活跃试炼"})
        rr["warning_shown_floor20"] = True
        p.stats["rogue_floor20_attempts"] = p.stats.get("rogue_floor20_attempts", 0)
        p.stats["rogue_run"] = rr
        save_wrapper()
        return fj({"ok":True,"rogue_run":rr})
    
    print("[Rogue] 星蚀试炼塔路由已注册")
