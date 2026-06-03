"""
星蚀试炼塔引擎 v2 — 难度选择→地图→战斗→返回
无次数限制 无钥匙消耗 统一敌人数值引擎
"""
import random, time, traceback
from datetime import date
from enemy_engine import (
    recommended_power_by_tier, generate_rogue_enemy,
    calc_enemy_power, ROGUE_MIN_POWER, ROGUE_MAX_POWER
)

ROGUE_FLOORS = 20

# ═══ 卡牌池 ═══
ROGUE_CARDS = [
    {"id":"atk_up","name":"火力增幅","type":"attack","quality":"common","desc":"攻击+8%","effect":"atk_pct","value":8},
    {"id":"dmg_up","name":"强袭弹","type":"attack","quality":"common","desc":"普攻伤害+12%","effect":"dmg_pct","value":12},
    {"id":"armor_break","name":"破甲弹","type":"attack","quality":"rare","desc":"无视18%护甲","effect":"ignore_armor","value":18},
    {"id":"double_shot","name":"双重射击","type":"attack","quality":"epic","desc":"每3回合额外攻击70%","effect":"extra_attack_3","value":70},
    {"id":"star_cannon","name":"星陨重炮","type":"attack","quality":"epic","desc":"每4回合伤害+100%","effect":"boost_4","value":100},
    {"id":"judge","name":"奇维鸟审判","type":"attack","quality":"legend","desc":"Boss伤害+35%,暴伤+35%","effect":"boss_crit","value":35},
    {"id":"eclipse_final","name":"星蚀终炮","type":"attack","quality":"mythic","desc":"首击250%,2回合敌受伤+20%","effect":"first_strike","value":250},
    {"id":"hp_up","name":"生命强化","type":"stat","quality":"common","desc":"最大生命+12%","effect":"hp_pct","value":12},
    {"id":"luck_up","name":"幸运羽毛","type":"stat","quality":"common","desc":"幸运+12%","effect":"luk_pct","value":12},
    {"id":"focus","name":"战斗专注","type":"stat","quality":"rare","desc":"暴击率+8%","effect":"crit_up","value":8},
    {"id":"extreme_fire","name":"极限火力","type":"stat","quality":"epic","desc":"攻击+25%,受伤+8%","effect":"atk25_dmg8","value":25},
    {"id":"steel_wing","name":"钢铁羽翼","type":"stat","quality":"epic","desc":"HP+22%,护甲+15%","effect":"hp_armor","value":22},
    {"id":"star_core","name":"星核共鸣","type":"stat","quality":"legend","desc":"全属性+15%","effect":"all_up","value":15},
    {"id":"shield","name":"厚羽护盾","type":"defense","quality":"common","desc":"开场HP8%护盾","effect":"start_shield","value":8},
    {"id":"heal_end","name":"应急包扎","type":"defense","quality":"common","desc":"战后恢复8%HP","effect":"end_heal","value":8},
    {"id":"unyielding","name":"不屈羽翼","type":"defense","quality":"epic","desc":"HP<30%恢复22%","effect":"low_hp_heal","value":22},
    {"id":"rage_flow","name":"怒气回流","type":"rage","quality":"common","desc":"每回合+8怒气","effect":"rage_per_turn","value":8},
    {"id":"war_spirit","name":"战意高涨","type":"rage","quality":"rare","desc":"开局+35怒气","effect":"start_rage","value":35},
    {"id":"regen","name":"轻微恢复","type":"heal","quality":"common","desc":"每回合回1.5%HP","effect":"regen","value":1.5},
    {"id":"life_drain","name":"生命汲取","type":"heal","quality":"rare","desc":"伤害8%转回血","effect":"lifesteal","value":8},
]

CARD_QUALITY = {"common":1,"rare":2,"epic":3,"legend":4,"mythic":5}

# ═══ 敌人技能池 ═══
ROGUE_ENEMY_SKILLS = {
    "normal": [
        {"name":"连续啄击","desc":"连续攻击2次,每次55%伤害","hits":2,"dmg_pct":55},
        {"name":"羽刃投射","desc":"120%伤害,下回合玩家受伤+10%","dmg_pct":120,"debuff":"dmg_taken_up"},
        {"name":"暗羽护体","desc":"获得12%HP护盾","shield_pct":12},
        {"name":"生命啄食","desc":"90%伤害,30%吸血","dmg_pct":90,"lifesteal":30},
    ],
    "elite": [
        {"name":"三连碎羽","desc":"连续攻击3次,每次45%","hits":3,"dmg_pct":45},
        {"name":"星蚀回血","desc":"恢复15%HP","heal_pct":15},
        {"name":"破甲尖啸","desc":"100%伤害,降护甲12%","dmg_pct":100,"armor_down":12},
    ],
    "boss": [
        {"name":"星蚀连击","desc":"连续攻击4次","hits":4,"dmg_pct":40},
        {"name":"黑羽再生","desc":"恢复18%HP","heal_pct":18},
        {"name":"终层护盾","desc":"获得20%HP护盾","shield_pct":20},
    ],
}

# ═══ 事件 ═══
ROGUE_EVENTS = [
    {"id":"altar","title":"星蚀祭坛","desc":"暗紫色的祭坛散发能量。",
     "choices":[
        {"id":"a","text":"献祭15%生命,攻击+12%","effect":"sacrifice_hp_atk","hp_cost_pct":15,"atk_gain":12},
        {"id":"b","text":"献祭3000金币,获稀有卡","effect":"sacrifice_gold_card","gold_cost":3000,"card_quality":"rare"},
        {"id":"c","text":"离开","effect":"none"},
     ]},
    {"id":"broken_jar","title":"破碎魔罐","desc":"开裂的天使魔罐透出光芒。",
     "choices":[
        {"id":"a","text":"打开(50%奖励,50%受伤)","effect":"gamble","win_chance":50,"win":{"gold":1500,"exp":300},"lose":{"hp_loss_pct":20}},
        {"id":"b","text":"跳过","effect":"none"},
     ]},
    {"id":"lost_kiwi","title":"迷失奇维鸟","desc":"瑟瑟发抖的小奇维鸟。",
     "choices":[
        {"id":"a","text":"帮助它,获得随机道具","effect":"help","reward":"random_item"},
        {"id":"b","text":"抢夺,金币+2000但受伤","effect":"rob","gold":2000,"hp_loss_pct":15},
        {"id":"c","text":"放它走,少量经验","effect":"release","exp":200},
     ]},
]

# ═══ 临时道具 ═══
TEMP_ITEMS = [
    {"id":"heal_potion","name":"星蚀药剂","desc":"恢复30%HP","effect":"heal","value":30},
    {"id":"armor_break_potion","name":"破甲药剂","desc":"下场无视25%护甲","effect":"ignore_armor_next","value":25},
    {"id":"revive_feather","name":"复苏羽毛","desc":"本次试炼致命伤复活1次","effect":"revive","value":30},
]

# ═══ 商店 ═══
SHOP_ITEMS = [
    {"id":"shop_heal","name":"治疗","desc":"恢复35%HP","cost_type":"tokens","cost":2,"effect":"heal","value":35},
    {"id":"shop_card","name":"随机稀有卡","desc":"稀有品质卡牌","cost_type":"tokens","cost":3,"effect":"random_card","quality":"rare"},
    {"id":"shop_atk","name":"攻击药剂","desc":"下场攻击+20%","cost_type":"tokens","cost":2,"effect":"atk_up_next","value":20},
]

NODE_TYPE_ICONS = {"monster":"⚔️","elite":"💀","event":"❓","item":"🎁","card":"🃏","shop":"🏪","rest":"🔥","boss":"👑"}
NODE_TYPE_COLORS = {"monster":"#4a90d9","elite":"#cc44ff","event":"#ffaa00","item":"#44cc66","card":"#9966ff","shop":"#ffcc00","rest":"#44cccc","boss":"#cc2222"}

# ═══ 地图生成(8-12节点+关底Boss) ═══
def generate_rogue_map(tier):
    """根据难度生成路线地图"""
    total_nodes = random.randint(8, 12)
    # 最后固定Boss
    node_types = []
    for i in range(total_nodes - 1):
        r = random.random()
        if r < 0.35: node_types.append("monster")
        elif r < 0.55: node_types.append("elite")
        elif r < 0.65: node_types.append("event")
        elif r < 0.75: node_types.append("card")
        elif r < 0.85: node_types.append("item")
        elif r < 0.93: node_types.append("shop")
        else: node_types.append("rest")
    node_types.append("boss")
    
    base_power = recommended_power_by_tier(tier)
    nodes = []
    for i, t in enumerate(node_types):
        is_boss = (i == total_nodes - 1)
        titles = {
            "monster":["星蚀幼鸟群","暗羽巡游者","裂空啄击者","深渊翼卫"],
            "elite":["星核守护者","暗翼统领","蚀渊巨喙"],
            "event":["星蚀祭坛","破碎魔罐","迷失奇维鸟"],
            "item":["星核补给箱","遗失军械库","能量结晶"],
            "card":["记忆回廊","战术复盘室","星能共鸣台"],
            "shop":["黑羽交易所","裂隙商栈"],
            "rest":["星辉营地","暖羽休憩所"],
            "boss":["终焉星蚀奇维鸟王"],
        }
        title = random.choice(titles.get(t, [f"{t}房"]))
        node = {
            "id": f"node_{i}",
            "index": i,
            "type": t,
            "title": title,
            "icon": NODE_TYPE_ICONS.get(t,"?"),
            "completed": False,
            "recommended_power": round(base_power * (1 + i * 0.05)),
            "sprite": "/picture/enemy/default.gif",
            "hue": random.randint(0, 359),
            "variant": "final_boss" if (t=="boss" and tier>=20) else ("boss" if t=="boss" else ("elite" if t=="elite" else "normal")),
        }
        nodes.append(node)
    
    # 建立线性连接(每节点只能前进到下一个)
    for i in range(len(nodes)-1):
        nodes[i]["next"] = [nodes[i+1]["id"]]
    nodes[-1]["next"] = []
    return nodes

def roll_rogue_cards(count=3, min_quality=None):
    pool = [c for c in ROGUE_CARDS if c["quality"]!="mythic" and c["quality"]!="legend"]
    if min_quality:
        min_q = CARD_QUALITY.get(min_quality,1)
        pool = [c for c in ROGUE_CARDS if CARD_QUALITY.get(c["quality"],1)>=min_q]
    if random.random() < 0.06:
        pool += [c for c in ROGUE_CARDS if c["quality"]=="mythic"]
    if random.random() < 0.12:
        pool += [c for c in ROGUE_CARDS if c["quality"]=="legend"]
    return random.sample(pool, min(count, len(pool)))

def calc_rogue_reward(tier, node_type, completed_nodes):
    """计算单场奖励: 普通怪极少, BOSS大量"""
    # 基础微量
    base_gold = 20 + tier * 6       # tier1=26, tier10=80, tier20=140
    base_exp = 30 + tier * 8         # tier1=38, tier10=110, tier20=190
    # 怪物极少, boss大量
    node_mult = {"monster":1.0,"elite":2.5,"event":0.2,"item":0.1,"card":0,"shop":0,"rest":0,"boss":12.0}
    tier_mult = 1.0 + tier * 0.08    # tier1=1.08, tier10=1.8, tier20=2.6
    gold = round(base_gold * node_mult.get(node_type,1.0) * tier_mult)
    exp = round(base_exp * node_mult.get(node_type,1.0) * tier_mult)
    return gold, exp

# ═══ 进度保存 ═══
def save_rogue_progress(p, rr):
    """保存试炼进度到player.stats"""
    p.stats["rogue_run"] = rr
    # 不调用外部的save_p,由调用方处理

# ═══ 路由注册 ═══
def register_rogue_routes(app, _player_ref, _save_fn, _pd_fn):
    """注册所有试炼塔路由"""
    from flask import jsonify as fj, request as fr
    
    def get_player():
        if hasattr(_player_ref, 'v'): return _player_ref.v
        return None
    
    def pd_wrapper():
        p = get_player()
        if not p: return {}
        try:
            return _pd_fn()
        except:
            return {"name":p.name,"level":p.level,"coins":p.coins,"power":0,"maxhp":p.maxhp}
    
    def save_wrapper():
        try: _save_fn()
        except Exception as e: print(f"[Rogue] Save failed: {e}")
    
    @app.route('/api/rogue/info', methods=['GET','POST'])
    @app.route('/api/rogue/state', methods=['GET','POST'])
    def api_rogue_info():
        p = get_player()
        if not p: return fj({"ok":False,"error":"未登录"})
        rr = p.stats.get("rogue_run") if hasattr(p,'stats') else None
        cp = p.power if p else 0
        tiers = []
        for t in range(1, 21):
            rp = recommended_power_by_tier(t)
            danger = "普通" if t<=5 else ("危险" if t<=10 else ("极危" if t<=15 else ("噩梦" if t<=19 else "终焉")))
            tiers.append({"tier":t,"recommended_power":rp,"reward_mult":round(1.0+t*0.25,2),"danger":danger})
        return fj({"ok":True,"min_power":ROGUE_MIN_POWER,"player_power":cp,
            "rogue_run":rr,"tiers":tiers,"can_enter":cp>=ROGUE_MIN_POWER})
    
    @app.route('/api/rogue/start', methods=['POST'])
    def api_rogue_start():
        p = get_player()
        if not p: return fj({"ok":False,"error":"未登录"})
        d = fr.get_json(force=True,silent=True) or {}
        tier = int(d.get("tier", 1))
        tier = max(1, min(20, tier))
        
        try: cp = p.power
        except: cp = 500
        if cp < ROGUE_MIN_POWER:
            return fj({"ok":False,"error":f"战斗力不足,最低需要{ROGUE_MIN_POWER}"})
        
        rmap = generate_rogue_map(tier)
        rr = {
            "active": True,
            "tier": tier,
            "map": rmap,
            "base_power": recommended_power_by_tier(tier),
            "current_node_index": -1,
            "available_node_ids": [rmap[0]["id"]],
            "completed_node_ids": [],
            "selected_cards": [],
            "upgraded_cards": [],
            "temporary_buffs": {},
            "temp_items": [],
            "tokens": 0,
            "accumulated_rewards": {"gold":0,"exp":0},
            "event_choices_made": {},
            "shop_purchases": {},
            "logs": [],
            "warning_shown": False,
        }
        p.stats["rogue_attempts"] = p.stats.get("rogue_attempts",0) + 1
        save_rogue_progress(p, rr)
        save_wrapper()
        return fj({"ok":True,"rogue_run":rr,"player":pd_wrapper()})
    
    @app.route('/api/rogue/enter_node', methods=['POST'])
    def api_rogue_enter_node():
        p = get_player()
        if not p: return fj({"ok":False,"error":"未登录"})
        d = fr.get_json(force=True,silent=True) or {}
        node_id = d.get("node_id","")
        rr = p.stats.get("rogue_run")
        if not rr or not rr.get("active"):
            return fj({"ok":False,"error":"无活跃试炼"})
        if node_id not in rr.get("available_node_ids",[]):
            return fj({"ok":False,"error":"无法到达此房间"})
        
        node = next((n for n in rr["map"] if n["id"]==node_id), None)
        if not node: return fj({"ok":False,"error":"房间不存在"})
        
        rr["current_node_index"] = node["index"]
        rr["current_node_id"] = node_id
        save_rogue_progress(p, rr)
        save_wrapper()
        
        room_type = node["type"]
        result = {"ok":True,"node":node,"room_type":room_type,
                  "player_power":p.power,"recommended_power":node.get("recommended_power",0)}
        
        if room_type in ("monster","elite","boss"):
            # 生成敌人
            completed = len(rr.get("completed_node_ids",[]))
            try: cp = p.power
            except: cp = 2000
            enemy = generate_rogue_enemy(rr["tier"], room_type, completed, player_power=cp)
            rr["current_enemy"] = enemy
            save_rogue_progress(p, rr)
            result["battle_ready"] = True
            result["enemy"] = enemy
            result["enemy_name"] = node["title"]
        elif room_type == "event":
            if node_id in rr.get("event_choices_made",{}):
                result["already_used"] = True
            else:
                result["event"] = random.choice(ROGUE_EVENTS)
        elif room_type == "item":
            result["item"] = random.choice(TEMP_ITEMS)
        elif room_type == "card":
            result["cards"] = roll_rogue_cards(3)
        elif room_type == "shop":
            result["shop_items"] = random.sample(SHOP_ITEMS, min(3,len(SHOP_ITEMS)))
            result["player_tokens"] = rr.get("tokens",0)
        elif room_type == "rest":
            cards = rr.get("selected_cards",[])
            result["rest_options"] = [
                {"id":"heal","text":"恢复35%HP","effect":"heal","value":35},
                {"id":"upgrade","text":"强化一张卡牌","effect":"upgrade_card","available":len(cards)>0},
            ]
        
        save_wrapper()
        return fj(result)
    
    @app.route('/api/rogue/battle/start', methods=['POST'])
    def api_rogue_battle_start():
        """初始化战斗状态,返回战斗页面所需数据"""
        p = get_player()
        if not p: return fj({"ok":False,"error":"未登录"})
        rr = p.stats.get("rogue_run")
        if not rr or not rr.get("active"):
            return fj({"ok":False,"error":"无活跃试炼"})
        node_id = rr.get("current_node_id")
        node = next((n for n in rr["map"] if n["id"]==node_id), None)
        if not node: return fj({"ok":False,"error":"请先进入房间"})
        if node.get("completed"): return advance_after_room(p, rr, node)
        
        enemy = rr.get("current_enemy")
        if not enemy:
            completed = len(rr.get("completed_node_ids",[]))
            try: cp = p.power
            except: cp = 2000
            enemy = generate_rogue_enemy(rr["tier"], node["type"], completed, player_power=cp)
            rr["current_enemy"] = enemy
        
        # 初始化战斗状态
        try: player_hp = p.maxhp
        except: player_hp = 2000
        enemy_hp = enemy["max_hp"]
        enemy_maxhp = enemy["max_hp"]
        enemy_power = enemy["power"]
        
        # 卡牌buff效果
        atk_bonus = 0; hp_bonus = 0
        for c in rr.get("selected_cards",[]):
            if c.get("effect")=="atk_pct": atk_bonus += c.get("value",0)
            if c.get("effect")=="hp_pct": hp_bonus += c.get("value",0)
        
        battle_state = {
            "player_hp": player_hp, "player_maxhp": p.maxhp,
            "enemy_hp": enemy_hp, "enemy_maxhp": enemy_maxhp,
            "enemy_name": node["title"], "enemy_power": enemy_power,
            "enemy_sprite": enemy.get("sprite",""), "enemy_hue": enemy.get("hue",0),
            "enemy_variant": enemy.get("variant","normal"),
            "enemy_type": node["type"],
            # 敌人6属性(用于前端展示)
            "enemy_atk": enemy.get("attack",0), "enemy_def": enemy.get("defense",0),
            "enemy_agi": enemy.get("agility",0), "enemy_luk": enemy.get("luck",0),
            "enemy_dmg": enemy.get("damage",0), "enemy_armor": enemy.get("armor",0),
            "attack_bonus": atk_bonus, "hp_bonus": hp_bonus,
            "turn": 1, "node_id": node_id,
        }
        rr["battle_state"] = battle_state
        save_rogue_progress(p, rr)
        save_wrapper()
        
        return fj({"ok":True,"battle":battle_state,"rogue_run":rr,"player":pd_wrapper()})
    
    @app.route('/api/rogue/battle/act', methods=['POST'])
    def api_rogue_battle_act():
        """玩家行动 + 敌人反击"""
        p = get_player()
        if not p: return fj({"ok":False,"error":"未登录"})
        rr = p.stats.get("rogue_run")
        if not rr or not rr.get("active"):
            return fj({"ok":False,"error":"无活跃试炼"})
        
        bs = rr.get("battle_state")
        if not bs: return fj({"ok":False,"error":"未开始战斗"})
        
        node_id = bs["node_id"]
        node = next((n for n in rr["map"] if n["id"]==node_id), None)
        
        d = fr.get_json(force=True,silent=True) or {}
        
        # === 玩家攻击 ===
        try: player_atk = max(300, p.atk)
        except: player_atk = 500
        player_atk = int(player_atk * (1 + bs.get("attack_bonus",0)/100))
        
        # 基础伤害 = 攻击力 * 随机倍率 * 暴击
        crit = random.random() < 0.15
        dmg_mult = random.uniform(0.8, 1.3) * (2.0 if crit else 1.0)
        player_dmg = max(1, int(player_atk * dmg_mult * 0.9))
        bs["enemy_hp"] = max(0, bs["enemy_hp"] - player_dmg)
        
        log_lines = []
        if crit: log_lines.append(f"💥 暴击! 你对{bs['enemy_name']}造成 {player_dmg} 伤害!")
        else: log_lines.append(f"⚔️ 你攻击{bs['enemy_name']},造成 {player_dmg} 伤害")
        
        enemy_dead = bs["enemy_hp"] <= 0
        
        if not enemy_dead:
            # === 敌人反击 ===
            enemy_atk = node.get("_enemy_atk") if node else None
            if not enemy_atk:
                enemy = rr.get("current_enemy",{})
                enemy_atk = enemy.get("damage",200)
            
            # 技能概率
            skill_used = None
            if random.random() < 0.35:
                skill_pool = ROGUE_ENEMY_SKILLS.get(node["type"] if node and node["type"] in ("elite","boss") else "normal",[])
                if skill_pool: skill_used = random.choice(skill_pool)
            
            if skill_used and skill_used.get("hits"):
                # 多段攻击
                total_dmg = 0
                for i in range(skill_used["hits"]):
                    hit_dmg = max(1, int(enemy_atk * (skill_used["dmg_pct"]/100) * random.uniform(0.7,1.0) * 0.12))
                    total_dmg += hit_dmg
                bs["player_hp"] = max(0, bs["player_hp"] - total_dmg)
                log_lines.append(f"🐦 {bs['enemy_name']}使用【{skill_used['name']}】{skill_used['hits']}连击,共造成 {total_dmg} 伤害!")
            elif skill_used and skill_used.get("heal_pct"):
                heal = int(bs["enemy_maxhp"] * skill_used["heal_pct"]/100)
                bs["enemy_hp"] = min(bs["enemy_maxhp"], bs["enemy_hp"] + heal)
                enemy_dmg = max(1, int(enemy_atk * random.uniform(0.6,1.0) * 0.6))
                bs["player_hp"] = max(0, bs["player_hp"] - enemy_dmg)
                log_lines.append(f"🐦 {bs['enemy_name']}使用【{skill_used['name']}】恢复{heal}HP, 攻击造成{enemy_dmg}伤害")
            else:
                enemy_dmg = max(1, int(enemy_atk * random.uniform(0.7,1.2) * 0.6))
                bs["player_hp"] = max(0, bs["player_hp"] - enemy_dmg)
                log_lines.append(f"🐦 {bs['enemy_name']}反击,造成 {enemy_dmg} 伤害")
            
            bs["skill_used"] = skill_used
        
        bs["turn"] = bs.get("turn",1) + 1
        player_dead = bs["player_hp"] <= 0
        
        won = enemy_dead and not player_dead
        
        result = {"ok":True,"won":won,"enemy_dead":enemy_dead,"player_dead":player_dead,
                  "player_dmg":player_dmg,"battle":bs,"logs":log_lines}
        
        if won or player_dead:
            # 战斗结束,立即发奖励
            gold, exp = calc_rogue_reward(rr["tier"], node["type"], len(rr.get("completed_node_ids",[])))
            result["gold"] = gold; result["exp"] = exp
            
            rr["accumulated_rewards"]["gold"] = rr["accumulated_rewards"].get("gold",0)+gold
            rr["accumulated_rewards"]["exp"] = rr["accumulated_rewards"].get("exp",0)+exp
            
            if won:
                p.coins += gold
                try: p.gain_exp(exp)
                except: pass
                node["completed"] = True
                rr["completed_node_ids"] = rr.get("completed_node_ids",[])+[node_id]
                rr["battle_state"] = None
                
                if node["type"]=="boss":
                    rr["active"] = False; rr["cleared"] = True
                    p.stats["rogue_boss_kills"] = p.stats.get("rogue_boss_kills",0)+1
                elif node["type"]=="elite":
                    p.stats["rogue_elite_kills"] = p.stats.get("rogue_elite_kills",0)+1
                
                result["cards"] = roll_rogue_cards(3) if node["type"] in ("elite","boss") or random.random()<0.35 else None
                
                adv = advance_after_room(p, rr, node)
                result.update({k:v for k,v in adv.items() if k not in result})
            else:
                rr["active"] = False
                rr["battle_state"] = None
                result["message"] = f"止步于{node['title']}"
            
            rr["logs"] = (rr.get("logs",[])+[f"{'✅ 胜利' if won else '💀 失败'} | 💰+{gold} ⭐+{exp}"])[-20:]
        
        save_rogue_progress(p, rr)
        save_wrapper()
        result["rogue_run"] = rr
        result["player"] = pd_wrapper()
        return fj(result)
    
    def advance_after_room(p, rr, node):
        """完成节点后前进"""
        next_ids = node.get("next",[])
        if not next_ids:
            rr["active"] = False
            rr["cleared"] = True
            p.stats["rogue_clears"] = p.stats.get("rogue_clears",0)+1
            return {"ok":True,"won":True,"node":node,"rogue_run":rr,
                    "cleared":True,"available_node_ids":[],
                    "message":"🏆 通关星蚀试炼塔！","player":pd_wrapper(),
                    "enemy_sprite":node.get("sprite",""),"enemy_hue":node.get("hue",0),
                    "enemy_variant":node.get("variant","normal")}
        
        rr["available_node_ids"] = next_ids
        rr["current_node_index"] = node["index"]+1
        rr["current_node_id"] = None
        rr["current_enemy"] = None
        return {"ok":True,"won":True,"node":node,"rogue_run":rr,
                "cleared":False,"available_node_ids":next_ids,
                "player":pd_wrapper(),"message":"选择下一个房间",
                "enemy_sprite":node.get("sprite",""),"enemy_hue":node.get("hue",0),
                "enemy_variant":node.get("variant","normal")}
    
    @app.route('/api/rogue/pick_card', methods=['POST'])
    def api_rogue_pick_card():
        p = get_player()
        d = fr.get_json(force=True,silent=True) or {}
        card_id = d.get("card_id","")
        rr = p.stats.get("rogue_run")
        if not rr: return fj({"ok":False,"error":"无活跃试炼"})
        card = next((c for c in ROGUE_CARDS if c["id"]==card_id), None)
        if card:
            rr["selected_cards"] = rr.get("selected_cards",[])+[card]
            rr["logs"].append(f"🃏 获得卡牌: {card['name']}")
        save_rogue_progress(p, rr)
        save_wrapper()
        return fj({"ok":True,"rogue_run":rr,"player":pd_wrapper()})
    
    @app.route('/api/rogue/event_choice', methods=['POST'])
    def api_rogue_event_choice():
        p = get_player()
        d = fr.get_json(force=True,silent=True) or {}
        evt_id, ch_id = d.get("event_id",""), d.get("choice_id","")
        rr = p.stats.get("rogue_run")
        if not rr: return fj({"ok":False,"error":"无活跃试炼"})
        node_id = rr.get("current_node_id","")
        if node_id in rr.get("event_choices_made",{}):
            return fj({"ok":False,"error":"已选择过"})
        
        evt = next((e for e in ROGUE_EVENTS if e["id"]==evt_id), None)
        if not evt: return fj({"ok":False,"error":"事件不存在"})
        choice = next((c for c in evt["choices"] if c["id"]==ch_id), None)
        if not choice: return fj({"ok":False,"error":"选项不存在"})
        
        result_msg = ""
        eff = choice.get("effect","")
        if eff == "sacrifice_hp_atk":
            rr["temporary_buffs"]["atk_bonus"] = rr["temporary_buffs"].get("atk_bonus",0)+choice["atk_gain"]
            result_msg = f"献祭生命,攻击+{choice['atk_gain']}%"
        elif eff == "sacrifice_gold_card":
            if p.coins >= choice["gold_cost"]:
                p.coins -= choice["gold_cost"]
                card = roll_rogue_cards(1, choice["card_quality"])[0]
                rr["selected_cards"] = rr.get("selected_cards",[])+[card]
                result_msg = f"获得卡牌:{card['name']}"
            else: result_msg = "金币不足"
        elif eff == "gamble":
            if random.randint(1,100) <= choice["win_chance"]:
                p.coins += choice["win"]["gold"]
                try: p.gain_exp(choice["win"]["exp"])
                except: pass
                result_msg = f"获得{choice['win']['gold']}金币+{choice['win']['exp']}经验"
            else:
                result_msg = f"破碎! 受到伤害"
        elif eff == "help":
            item = random.choice(TEMP_ITEMS)
            rr["temp_items"] = rr.get("temp_items",[])+[item]
            result_msg = f"获得道具:{item['name']}"
        elif eff == "rob":
            p.coins += choice["gold"]
            result_msg = f"抢夺{choice['gold']}金币"
        elif eff == "release":
            try: p.gain_exp(choice["exp"])
            except: pass
            result_msg = f"获得{choice['exp']}经验"
        else: result_msg = "无事发生"
        
        rr["event_choices_made"] = rr.get("event_choices_made",{})
        rr["event_choices_made"][node_id] = ch_id
        rr["logs"].append(f"❓ {evt['title']}: {result_msg}")
        
        node = next((n for n in rr["map"] if n["id"]==node_id), None)
        if node: node["completed"] = True
        rr["completed_node_ids"] = rr.get("completed_node_ids",[])+[node_id]
        
        save_rogue_progress(p, rr)
        save_wrapper()
        
        result = advance_after_room(p, rr, node) if node else {}
        result["event_result"] = result_msg
        return fj(result)
    
    @app.route('/api/rogue/item_claim', methods=['POST'])
    def api_rogue_item_claim():
        p = get_player()
        d = fr.get_json(force=True,silent=True) or {}
        item_id = d.get("item_id","")
        rr = p.stats.get("rogue_run")
        if not rr: return fj({"ok":False,"error":"无活跃试炼"})
        node_id = rr.get("current_node_id","")
        if node_id in rr.get("completed_node_ids",[]):
            return fj({"ok":False,"error":"已领取过"})
        item = next((it for it in TEMP_ITEMS if it["id"]==item_id), None)
        if not item: return fj({"ok":False,"error":"道具不存在"})
        rr["temp_items"] = rr.get("temp_items",[])+[item]
        node = next((n for n in rr["map"] if n["id"]==node_id), None)
        if node: node["completed"] = True
        rr["completed_node_ids"] = rr.get("completed_node_ids",[])+[node_id]
        rr["logs"].append(f"🎁 获得: {item['name']}")
        save_rogue_progress(p, rr)
        save_wrapper()
        result = advance_after_room(p, rr, node) if node else {}
        result["item_received"] = item["name"]
        return fj(result)
    
    @app.route('/api/rogue/shop_buy', methods=['POST'])
    def api_rogue_shop_buy():
        p = get_player()
        d = fr.get_json(force=True,silent=True) or {}
        item_id = d.get("item_id","")
        rr = p.stats.get("rogue_run")
        if not rr: return fj({"ok":False,"error":"无活跃试炼"})
        node_id = rr.get("current_node_id","")
        
        si = next((s for s in SHOP_ITEMS if s["id"]==item_id), None)
        if not si: return fj({"ok":False,"error":"商品不存在"})
        
        purchases = rr.get("shop_purchases",{})
        if node_id in purchases and item_id in purchases.get(node_id,[]):
            return fj({"ok":False,"error":"已购买过"})
        
        cost_type, cost = si["cost_type"], si["cost"]
        if cost_type == "tokens":
            if rr.get("tokens",0) < cost: return fj({"ok":False,"error":"星蚀徽章不足"})
            rr["tokens"] = rr.get("tokens",0)-cost
        else:
            if p.coins < cost: return fj({"ok":False,"error":"金币不足"})
            p.coins -= cost
        
        result_msg = ""
        if si["effect"] == "heal": result_msg = f"恢复35%HP"
        elif si["effect"] == "random_card":
            card = roll_rogue_cards(1, si["quality"])[0]
            rr["selected_cards"] = rr.get("selected_cards",[])+[card]
            result_msg = f"获得卡牌:{card['name']}"
        elif si["effect"] == "atk_up_next":
            rr["temporary_buffs"]["shop_atk_up"] = True
            result_msg = "下场攻击+20%"
        
        rr["shop_purchases"] = rr.get("shop_purchases",{})
        if node_id not in rr["shop_purchases"]: rr["shop_purchases"][node_id] = []
        rr["shop_purchases"][node_id].append(item_id)
        rr["logs"].append(f"🏪 {si['name']}: {result_msg}")
        save_rogue_progress(p, rr)
        save_wrapper()
        return fj({"ok":True,"result":result_msg,"rogue_run":rr,"player":pd_wrapper()})
    
    @app.route('/api/rogue/shop_leave', methods=['POST'])
    def api_rogue_shop_leave():
        p = get_player()
        rr = p.stats.get("rogue_run")
        if not rr: return fj({"ok":False,"error":"无活跃试炼"})
        node_id = rr.get("current_node_id","")
        node = next((n for n in rr["map"] if n["id"]==node_id), None)
        if node: node["completed"] = True
        rr["completed_node_ids"] = rr.get("completed_node_ids",[])+[node_id]
        save_rogue_progress(p, rr)
        save_wrapper()
        return fj(advance_after_room(p, rr, node) if node else {})
    
    @app.route('/api/rogue/rest', methods=['POST'])
    def api_rogue_rest():
        p = get_player()
        d = fr.get_json(force=True,silent=True) or {}
        action = d.get("action","")
        card_id = d.get("card_id","")
        rr = p.stats.get("rogue_run")
        if not rr: return fj({"ok":False,"error":"无活跃试炼"})
        node_id = rr.get("current_node_id","")
        if node_id in rr.get("completed_node_ids",[]):
            return fj({"ok":False,"error":"已使用过"})
        
        result_msg = ""
        if action == "skip":
            result_msg = "跳过休息"
        elif action == "heal":
            result_msg = "恢复35%HP"
        elif action == "upgrade":
            if card_id and rr.get("selected_cards"):
                for c in rr["selected_cards"]:
                    if c["id"]==card_id and card_id not in rr.get("upgraded_cards",[]):
                        c["value"] = int(c["value"]*1.5)
                        rr["upgraded_cards"] = rr.get("upgraded_cards",[])+[card_id]
                        result_msg = f"强化了{c['name']}"
                        break
        
        node = next((n for n in rr["map"] if n["id"]==node_id), None)
        if node: node["completed"] = True
        rr["completed_node_ids"] = rr.get("completed_node_ids",[])+[node_id]
        rr["logs"].append(f"🔥 休息: {result_msg}")
        p.stats["rogue_rests_used"] = p.stats.get("rogue_rests_used",0)+1
        save_rogue_progress(p, rr)
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
            save_rogue_progress(p, rr)
        save_wrapper()
        return fj({"ok":True,"rogue_run":rr,"player":pd_wrapper()})
    
    @app.route('/api/rogue/boss_warning', methods=['POST'])
    def api_rogue_boss_warning():
        p = get_player()
        rr = p.stats.get("rogue_run")
        if rr:
            rr["warning_shown"] = True
            save_rogue_progress(p, rr)
        save_wrapper()
        return fj({"ok":True,"rogue_run":rr})
    
    print("[Rogue v2] 星蚀试炼塔路由已注册(无限次/无钥匙/难度选择)")
