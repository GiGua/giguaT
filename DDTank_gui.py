#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DDTank GUI v4 — 装备系统·Capoo/Kiwi敌人·强化石·头像·性别"""

import json, os, random, time, math, sys, re, threading, webbrowser, base64, glob, hashlib, shutil, socket, uuid, datetime as _dt
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum
from flask import Flask, jsonify, request, send_from_directory, send_file

# ═══ PostgreSQL 支持 ═══
DATABASE_URL = os.environ.get("DATABASE_URL")
use_pg = False
pg_conn = None
Jsonb = None  # psycopg.types.json.Jsonb, set in init_db()

def init_db():
    """初始化数据库（PostgreSQL优先，本地auth.json fallback）"""
    global use_pg, pg_conn, Jsonb
    if not DATABASE_URL:
        print("[DB] No DATABASE_URL → using local saves/auth.json")
        return
    try:
        import psycopg
        from psycopg.types.json import Jsonb as _Jsonb
        Jsonb = _Jsonb
        pg_conn = psycopg.connect(DATABASE_URL)
        use_pg = True
        with pg_conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS player_saves (
                    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    save_data JSONB NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        pg_conn.commit()
        print(f"[DB] PostgreSQL connected ({DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else DATABASE_URL}), tables ready")
    except Exception as e:
        print(f"[DB] PostgreSQL init failed: {e} → falling back to local auth.json")
        use_pg = False
        pg_conn = None

# ═══════════════════ 数据定义 ═══════════════════

APP_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
RESOURCE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
SAVE_DIR = APP_DIR
SAVE_FILE = os.path.join(SAVE_DIR, "save.json")

# ═══ 真人玩家存档系统：只保存用户/玩家 profile，不混入模拟 AI ═══
SAVES_DIR = os.path.join(SAVE_DIR, "saves")
PROFILES_FILE = os.path.join(SAVES_DIR, "profiles.json")
ACTIVE_PROFILE_ID = None  # 当前活跃存档ID
DB_USER_ID = None  # PostgreSQL users.id (用于 save_p 直接写入)

def ensure_saves_dir():
    if not os.path.exists(SAVES_DIR): os.makedirs(SAVES_DIR)

def load_profiles():
    ensure_saves_dir()
    if os.path.exists(PROFILES_FILE):
        try:
            with open(PROFILES_FILE,'r',encoding='utf-8') as f:return json.load(f)
        except:pass
    return {"active_profile_id":None,"profiles":[]}

def save_profiles(data):
    ensure_saves_dir()
    with open(PROFILES_FILE,'w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)

def get_profile_path(pid):
    return os.path.join(SAVES_DIR,f"profile_{pid}.json")

def load_profile(pid):
    pp=get_profile_path(pid)
    if os.path.exists(pp):
        try:
            with open(pp,'r',encoding='utf-8') as f:return Character.from_dict(json.load(f))
        except:pass
    return None

def save_profile(p,pid):
    ensure_saves_dir()
    with open(get_profile_path(pid),'w',encoding='utf-8') as f:json.dump(p.to_dict(),f,ensure_ascii=False,indent=2)

def migrate_legacy_save():
    """迁移旧save.json到新存档系统"""
    if not os.path.exists(SAVE_FILE):return None
    try:
        with open(SAVE_FILE,'r',encoding='utf-8') as f:data=json.load(f)
        import uuid,datetime
        pid=str(uuid.uuid4())[:8]
        c=Character.from_dict(data)
        now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_profile(c,pid)
        profiles=load_profiles()
        profiles["profiles"].append({"id":pid,"display_name":c.name,"created_at":now,"updated_at":now,"level":c.level,"avatar_preview":c.avatar[:50] if c.avatar else "","note":"(从旧存档迁移)"})
        profiles["active_profile_id"]=pid
        save_profiles(profiles)
        os.rename(SAVE_FILE,SAVE_FILE+".migrated")
        return pid
    except Exception as e:
        print(f"迁移旧存档失败: {e}")
        return None

# ═══ 战斗力系统 ═══

WEAPON_TYPE_SCORE = {"sniper":120,"light":90,"standard":100,"heavy":130,"multi":140,"control":150,"dot":130,"support":120}
RARITY_SCORE = {0:0, 1:80, 2:180, 3:350, 4:600, 5:850}

def calculate_combat_power(p):
    """战斗力计算, 返回 {total, breakdown}"""
    # 基础属性
    base = p.maxhp*0.25 + p.atk*7.5 + p.defense*5.0 + p.agility*3.2 + p.luk*3.0 + p.wdmg*4.0
    # 暴击命中
    crit_p = p.crit_rate*1200 if p.crit_rate<1 else (p.crit_rate/100)*1200
    acc_p = 0  # accuracy not tracked separately yet
    # 武器机制
    w = p.weapon
    wtype_s = WEAPON_TYPE_SCORE.get(w.weapon_type, 100) if w and hasattr(w, 'weapon_type') else 100
    rarity_s = RARITY_SCORE.get(w.quality.value, 0) if w and hasattr(w, 'quality') else 0
    weapon_p = wtype_s + rarity_s
    # 坑能力
    pit_p = min(250, (w.pit_radius*2 + w.pit_depth*1.5)) if w else 0
    if w and w.projectile_count>1: pit_p = min(250, pit_p * 1.2)  # 多段按总上限
    # 强化
    elv,_ = p.get_enhance()
    enhance_p = elv*35 + int(elv**1.25*12)
    equip_enh = sum((20 + int(8)) for _ in range(4))  # 简化装备强化
    # 成就
    ach_p = min(500, p.wins*8 + p.dungeon_clears*12 + p.level*20)
    total = int(base + crit_p + acc_p + weapon_p + pit_p + enhance_p + equip_enh + ach_p)
    return {"total":total,"breakdown":{"base_stats":int(base),"weapon":int(weapon_p),"equipment":int(equip_enh),"enhancement":int(enhance_p),"special_effect":int(pit_p),"achievement":int(ach_p)}}

def update_profile_combat_power(pid):
    p = load_profile(pid)
    if not p: return
    cp = calculate_combat_power(p)
    # 存入profile文件
    data = p.to_dict()
    data["combat_power"] = cp["total"]
    data["combat_power_breakdown"] = cp["breakdown"]
    data["combat_power_updated_at"] = datetime.datetime.now().isoformat()
    with open(get_profile_path(pid),'w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)

# ═══ 排行榜系统 ═══
LEADERBOARD_FILE = os.path.join(SAVE_DIR, "leaderboard_cache.json")
NPC_RANKERS = [
    {"name":"卡波大师","base_lv":18,"base_cp":4200,"growth":0.3,"avatar":"capoo","weapon":"真·牛头怪","seed":1},
    {"name":"几维鸟勇者","base_lv":15,"base_cp":3600,"growth":0.25,"avatar":"kiwi","weapon":"炽天使轨道炮","seed":2},
    {"name":"暗影刺客","base_lv":12,"base_cp":2800,"growth":0.35,"avatar":"capoo","weapon":"黑洞重力炮","seed":3},
    {"name":"雷霆战神","base_lv":22,"base_cp":5200,"growth":0.20,"avatar":"capoo","weapon":"雷霆审判炮","seed":4},
    {"name":"深海领主","base_lv":20,"base_cp":4800,"growth":0.28,"avatar":"kiwi","weapon":"深海龙息弩","seed":5},
]

def get_dynamic_npc(npc):
    """根据时间生成动态NPC属性（每天有小幅自然增长）"""
    import math, time
    days = time.time() / 86400  # 从epoch算起的天数
    seed = npc["seed"]
    # 用sin曲线产生小幅波动（±15%）
    fluctuation = math.sin(days / 3 + seed * 1.7) * 0.15
    growth = 1 + days * npc["growth"] * 0.0005 + fluctuation  # 每天增长0.05%
    lv = max(1, int(npc["base_lv"] * growth))
    cp = int(npc["base_cp"] * growth)
    wins = int(20 + days * 0.1 + math.sin(days / 5 + seed) * 5)
    return {
        "name": npc["name"], "level": lv, "combat_power": cp,
        "avatar": npc["avatar"], "weapon_name": npc["weapon"],
        "wins": int(wins), "dungeon_clears": int(wins * 0.4),
        "is_npc": True
    }

def load_leaderboard_cache():
    if os.path.exists(LEADERBOARD_FILE):
        try:
            with open(LEADERBOARD_FILE,'r',encoding='utf-8') as f:return json.load(f)
        except:pass
    return {"last_refresh_at":None,"rankings":{"combat_power":[],"level":[]},"previous_rankings":{"combat_power":[],"level":[]}}

def save_leaderboard_cache(cache):
    with open(LEADERBOARD_FILE,'w',encoding='utf-8') as f:json.dump(cache,f,ensure_ascii=False,indent=2)

def should_refresh_leaderboard():
    import datetime as _dt
    now = _dt.datetime.now()
    cache = load_leaderboard_cache()
    last_str = cache.get("last_refresh_at")
    if not last_str: return True
    try:
        last = _dt.datetime.fromisoformat(last_str)
        return (now - last).total_seconds() >= 30 * 60  # 30分钟
    except: return True

def refresh_leaderboard(force=False):
    import datetime as _dt
    if not force and not should_refresh_leaderboard():
        return load_leaderboard_cache()
    now = _dt.datetime.now()
    next_refresh = now + _dt.timedelta(minutes=30)
    
    # 读取所有profile + PostgreSQL player_saves
    profiles = load_profiles()
    players = []
    
    # ─── PostgreSQL: 读取所有玩家存档 ───
    if use_pg and pg_conn:
        try:
            with pg_conn.cursor() as cur:
                cur.execute("SELECT u.username, ps.save_data FROM users u JOIN player_saves ps ON u.id=ps.user_id")
                rows = cur.fetchall()
            for username, save_data in rows:
                if isinstance(save_data, str): save_data = json.loads(save_data)
                elif not isinstance(save_data, dict): continue
                c = Character.from_dict(save_data)
                cp_val = save_data.get("combat_power", 0)
                if cp_val == 0: cp_val = calculate_combat_power(c)["total"]
                pid = save_data.get("profile_id", "pg_"+username)
                players.append({
                    "profile_id": pid, "display_name": username,
                    "avatar": c.avatar, "level": c.level, "exp": c.exp,
                    "combat_power": cp_val, "weapon_name": c.weapon.name if c.weapon else "无",
                    "rating": c.rating, "wins": c.wins, "dungeon_clears": c.dungeon_clears,
                    "is_npc": False, "is_current": False, "is_bot": False
                })
            print(f"[LB] Loaded {len(rows)} players from PostgreSQL")
        except Exception as e:
            print(f"[LB] PG load error: {e}")
    
    # ─── 本地 fallback (去重：跳过PG已有用户) ───
    pg_names = {p["display_name"] for p in players}
    for pr in profiles.get("profiles",[]):
        p = load_profile(pr["id"])
        if not p: continue
        if p.name in pg_names: continue  # PG已有，跳过
        data = p.to_dict()
        cp_val = data.get("combat_power",0)
        if cp_val == 0:
            cpc = calculate_combat_power(p); cp_val = cpc["total"]
        players.append({"profile_id":pr["id"],"display_name":p.name,"avatar":p.avatar,"level":p.level,"exp":p.exp,
            "combat_power":cp_val,"weapon_name":p.weapon.name if p.weapon else "无","rating":p.rating,
            "wins":p.wins,"dungeon_clears":p.dungeon_clears,"is_npc":False,"is_current":False,"is_bot":False})
    
    # 加入bot玩家
    bot_profiles = load_bot_profiles()
    for bot in bot_profiles.get("bots",[]):
        ensure_bot_local_avatar(bot)
        players.append({"profile_id":bot["bot_id"],"display_name":bot["display_name"],"avatar":bot.get("avatar",""),
            "level":bot.get("level",1),"exp":bot.get("exp",0),"combat_power":bot.get("combat_power",0),
            "weapon_name":WEAPONS.get(bot.get("weapon_id",""),None).name if bot.get("weapon_id") in WEAPONS else bot.get("weapon_id","无"),
            "rating":bot.get("rating",1000),
            "wins":bot.get("material",{}).get("wins",0) if isinstance(bot.get("material"),dict) else 0,
            "dungeon_clears":0,"is_npc":False,"is_current":False,"is_bot":True})
    
    # NPC 根据数量动态决定是否加入
    if len(players) < 5:
        max_cp = max((pl["combat_power"] for pl in players),default=3000)
        for npc in NPC_RANKERS:
            n = get_dynamic_npc(npc)
            n["profile_id"] = "npc_" + str(n.get("name","npc"))
            n["display_name"] = n.get("name","NPC")
            n["avatar"] = local_ai_avatar(n["profile_id"])
            players.append(n)
    
    all_entries = players
    for entry in all_entries:
        ensure_entry_local_avatar(entry)
    # 战斗力排名
    cp_rank = sorted(all_entries, key=lambda x:(-x["combat_power"],-x["level"],-x.get("exp",0),-x.get("wins",0),x["profile_id"] if x.get("profile_id") else x["name"]))
    for i,entry in enumerate(cp_rank): entry["rank"]=i+1
    
    # 等级排名
    lv_rank = sorted(all_entries, key=lambda x:(-x["level"],-x.get("exp",0),-x["combat_power"],-x.get("dungeon_clears",0),x["profile_id"] if x.get("profile_id") else x["name"]))
    for i,entry in enumerate(lv_rank): entry["rank"]=i+1
    
    # 计算排名变化
    prev_cache = load_leaderboard_cache()
    prev_cp = {e.get("profile_id") or e["name"]:e["rank"] for e in prev_cache.get("rankings",{}).get("combat_power",[])}
    for entry in cp_rank:
        pid_key = entry.get("profile_id") or entry["name"]
        old_rank = prev_cp.get(pid_key)
        entry["rank_change"] = old_rank-entry["rank"] if old_rank else 0
    
    cache = {"last_refresh_at":now.isoformat(),"next_refresh_at":next_refresh.isoformat(),
        "refresh_interval_minutes":30,"rankings":{"combat_power":cp_rank,"level":lv_rank},
        "previous_rankings":prev_cache.get("rankings",{})}
    save_leaderboard_cache(cache)
    return cache

# ═══ AI Bot 玩家系统 ═══
# 模拟 AI 单独存档，不和真人玩家 profile 混在一起。
BOTS_DIR = os.path.join(SAVE_DIR, "ai_saves")
LEGACY_BOTS_DIR = os.path.join(SAVE_DIR, "bots")
BOT_PROFILES_FILE = os.path.join(BOTS_DIR, "bot_profiles.json")
BOT_CHAT_FILE = os.path.join(BOTS_DIR, "bot_chat_log.json")
BOT_ANNOUNCE_FILE = os.path.join(BOTS_DIR, "bot_announcements.json")

PREFIX_NAMES = ["星河","月影","奶糖","风铃","青柠","夜雨","小熊","白桃","流萤","琉璃","晨曦","暮雪","浅梦","半夏","南鸢","晴川","洛洛","七海","千羽","桃桃","雾岛","蓝莓","云雀","霜华","紫苏"]
SUFFIX_NAMES = ["猫猫","勇者","小炮手","魔罐王","强化大师","几维鸟","卡波","小锤子","欧皇","咸鱼","战士","游侠","法师","刺客","守护者","弹客","小魔女","冒险家","狙击手","小骑士","团子","旅人","星尘","小队长","猎手"]
BOT_PERSONALITIES = ["努力型","欧皇型","强化狂","竞技型","收藏型","咸鱼型"]

def is_test_name(name):
    bad = ["stress","test","testbot","releasetest","api_test","droptest","dummy","p2","rc_test","profile_test"]
    clean = name.lower().replace(" ","").replace("_","").replace("-","")
    return any(x in clean for x in bad)

def ensure_bots_dir():
    if not os.path.exists(BOTS_DIR): os.makedirs(BOTS_DIR)
    legacy_profiles = os.path.join(LEGACY_BOTS_DIR, "bot_profiles.json")
    if not os.path.exists(BOT_PROFILES_FILE) and os.path.exists(legacy_profiles):
        shutil.copy2(legacy_profiles, BOT_PROFILES_FILE)

def load_bot_profiles():
    ensure_bots_dir()
    if os.path.exists(BOT_PROFILES_FILE):
        try:
            with open(BOT_PROFILES_FILE,'r',encoding='utf-8') as f:
                data = json.load(f)
            changed = False
            for bot in data.get("bots",[]):
                changed = ensure_bot_local_avatar(bot) or changed
            if changed: save_bot_profiles(data)
            return data
        except:pass
    return {"last_simulation_at":None,"bots":[]}

def save_bot_profiles(data):
    ensure_bots_dir()
    with open(BOT_PROFILES_FILE,'w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)

def generate_bot_name():
    import random as _r
    return _r.choice(PREFIX_NAMES)+_r.choice(SUFFIX_NAMES)

AI_AVATAR_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")

def list_ai_avatar_files():
    ai_dir = rp2(os.path.join("picture", "ai"))
    if not os.path.isdir(ai_dir):
        return []
    files = []
    for name in os.listdir(ai_dir):
        if name.lower().endswith(AI_AVATAR_EXTS):
            files.append(name)
    files.sort()
    return files

def local_ai_avatar(seed=None):
    files = list_ai_avatar_files()
    if not files:
        return "picture/defaults/default_avatar.png"
    if seed:
        digest = hashlib.md5(str(seed).encode("utf-8")).hexdigest()
        idx = int(digest[:8], 16) % len(files)
    else:
        idx = random.randrange(len(files))
    return "picture/ai/" + files[idx]

def bot_avatar_needs_local_ai(avatar):
    if not avatar:
        return True
    a = str(avatar).strip().replace("\\", "/").lower()
    return not a.startswith("picture/ai/")

def ensure_bot_local_avatar(bot):
    if bot_avatar_needs_local_ai(bot.get("avatar", "")):
        bot["avatar"] = local_ai_avatar(bot.get("bot_id") or bot.get("display_name"))
        return True
    return False

def ensure_entry_local_avatar(entry):
    if entry.get("is_bot") or entry.get("is_npc"):
        if bot_avatar_needs_local_ai(entry.get("avatar", "")):
            entry["avatar"] = local_ai_avatar(entry.get("profile_id") or entry.get("display_name") or entry.get("name"))
            return True
    return False

def generate_bot_avatar_url(bot_id=None):
    return local_ai_avatar(bot_id)

def download_loli_avatar(bot_id):
    return {"success": True, "avatar": local_ai_avatar(bot_id), "source": "picture/ai"}

def generate_bots(count=50):
    data = load_bot_profiles()
    existing_names = {b["display_name"] for b in data["bots"]}
    # 清理测试名
    data["bots"] = [b for b in data["bots"] if not is_test_name(b.get("display_name",""))]
    weapons = ["fire","boom","wind","lightning","sima","tv","medkit","plunger","fruit"]
    import datetime as _dt
    for i in range(count):
        name = generate_bot_name()
        while name in existing_names or is_test_name(name): name = generate_bot_name()
        existing_names.add(name)
        lv = random.randint(1,10)  # 初始等级降低，更真实
        wid = random.choice(weapons)
        cp_base = lv*200 + random.randint(800,4000)
        # 使用LoliApi下载头像(分批,不阻塞)
        new_bot_id = f"bot_{len(data['bots'])+1:04d}"
        avatar_result = download_loli_avatar(new_bot_id)
        avatar = avatar_result.get("avatar","")
        bot = {"bot_id":f"bot_{len(data['bots'])+1:04d}","display_name":name,"avatar":avatar,
            "level":lv,"exp":random.randint(0,lv*100),"gold":random.randint(500,lv*800),
            "rating":random.randint(980,1350)+lv*18,
            "combat_power":cp_base,"weapon_id":wid,"weapon_enhances":{wid:random.randint(0,min(5,lv))},
            "owned_weapons":[wid]+random.sample([w for w in weapons if w!=wid],min(2,len(weapons)-1)),
            "owned_equipment":[],"materials":{"angel_pot":random.randint(0,3),"angel_hammer":random.randint(5,15),
            "silver_pot":0,"gold_pot":0,"enhance_small":random.randint(0,5),"enhance_medium":0,
            "enhance_large":0,"magic_can_fragment":random.randint(0,20)},
            "personality":random.choice(BOT_PERSONALITIES),"play_style":"balanced","activity_level":random.uniform(0.3,1.0),
            "last_active_at":_dt.datetime.now().isoformat(),"is_bot":True}
        data["bots"].append(bot)
    save_bot_profiles(data)
    return data

def simulate_bot_actions(steps=1):
    """模拟bot行为,返回聊天和公告"""
    # 扩充消息池(每次调用复用)
    if 'CHAT_POOLS' not in globals():
        globals()['CHAT_POOLS'] = {
            "arena": ["今天手感不错！","这局打得激烈","有人来一把吗？","看我的新武器！","刚刚拿了个三杀！","这把匹配的对手好强","竞技场排名又掉了","今天拿了几连胜","来切磋一把？","战力终于破千了","这把运气真好","被暴击秒了","我Rating多少了","有人一起排吗","这届竞技场好卷","又来练手了","今天要冲王者","竞技场日常打卡","求轻虐","差点就赢了"],
            "pot": ["开罐真刺激！","这次运气不错","又没出好东西…","攒罐子等下次","刚开出个神器！","50连开了，就一个橙","金罐概率太低了","碎片攒够了吗","求欧气","今天适合开罐","有人出过神话吗","罐子全空了","终于出传说了","开罐上瘾了","银罐也不错的","金色传说！","我是不是该去洗脸","连开十个蓝天白云","今天罐子爆率好低","老板再来一罐"],
            "world": ["今天天气不错","大家都在干嘛呢","强化好难啊","副本掉落太看脸了","排行榜又更新了","新人求带副本","商店上新武器了","有没有公会收人","这游戏真好玩","大佬们好","萌新报道","战力怎么提升快","金币不够用了","强化石去哪刷","求副本攻略","有人出神话武器吗","这游戏太肝了","休闲玩家路过","今天签到领了什么","晚上人多吗","周末有活动吗","武器碎片好难攒","装备怎么搭配","强化到+15要多少石头","战力排行榜第一是谁","副本boss怎么打","竞技场遇到大佬了","有没有速刷攻略","今天运气爆棚","肝帝的一天开始了"],
            "dungeon": ["副本好难","刚通关了！","这boss太猛了","掉落不错","翻卡翻到神器！","副本奖励还行","又跪在boss关了","求组队打副本","今天副本刷什么","几维鸟好可爱","深渊副本有人过吗","副本经验真多","掉落概率太低了","终于通关深谷了","副本金币真香","草窝副本最简单","火山坡好难","大佬带带副本","今天刷了多少次","副本一天能打几次"],
            "enhance": ["强化失败了好多次","强化成功+12了！","强化石不够用","求强化技巧","终于+15了","武器强化太烧金币","强化概率是假的吧","连碎5次了","有人能帮强化吗","今天的强化运气不错","+10之后好难","强化材料去哪刷","有没有强化保底","强化让我破产了","今天成功+8了"],
            "shop": ["商店上新了！","买个新武器试试","装备好贵","金币不够买","这个武器值不值","商店什么时候更新","攒钱中","买了把新武器","装备该换了","商店有打折吗"]
        }
    data = load_bot_profiles()
    if not data["bots"]: data = generate_bots(50)
    import datetime as _dt
    now = _dt.datetime.now()
    chat_log = load_chat_log()
    announcements = load_announcements()
    
    for step in range(steps):
        for bot in data["bots"]:
            if random.random() > bot.get("activity_level",0.5): continue
            action = random.choices(["arena","dungeon","pot","enhance","shop","chat"],
                weights=[0.30,0.25,0.15,0.15,0.05,0.10],k=1)[0]
            mats = bot.get("materials",{})
            if action == "arena":
                bot["exp"] = bot.get("exp",0)+random.randint(10,50)
                bot["gold"] = bot.get("gold",0)+random.randint(20,100)
                if bot["exp"] >= bot["level"]*100: bot["level"]+=1;bot["exp"]=0
                mats["angel_hammer"] = mats.get("angel_hammer",0)+(1 if random.random()<0.35 else 0)
                mats["angel_pot"] = mats.get("angel_pot",0)+(1 if random.random()<0.10 else 0)
                mats["magic_can_fragment"] = mats.get("magic_can_fragment",0)+random.randint(0,3)
                if random.random()<0.1: chat_log.append({"time":now.isoformat(),"name":bot["display_name"],"channel":"arena","msg":random.choice(CHAT_POOLS["arena"]),"is_bot":True})
            elif action == "dungeon":
                bot["exp"] = bot.get("exp",0)+random.randint(20,80)
                bot["gold"] = bot.get("gold",0)+random.randint(30,150)
                mats["angel_hammer"] = mats.get("angel_hammer",0)+(1 if random.random()<0.25 else 0)
            elif action == "pot":
                if mats.get("angel_pot",0)>0 and mats.get("angel_hammer",0)>=4:
                    mats["angel_pot"]-=1;mats["angel_hammer"]-=4
                    bot["angel_open_count"]=bot.get("angel_open_count",0)+1
                    # bot开罐不再公告，只记录
                    if random.random()<0.1: chat_log.append({"time":now.isoformat(),"name":bot["display_name"],"channel":"pot","msg":random.choice(CHAT_POOLS["pot"]),"is_bot":True})
            elif action == "enhance":
                elv = bot.get("weapon_enhances",{}).get(bot.get("weapon_id","fire"),0)
                if mats.get("enhance_small",0)>0:
                    mats["enhance_small"]-=1
                    if random.random()<0.4: bot["weapon_enhances"][bot.get("weapon_id","fire")]=elv+1
                if elv>=20: announcements.append({"time":now.isoformat(),"msg":f"🔥 【{bot['display_name']}】强化成功！武器达到 +{elv+1}！","type":"enhance"})
            elif action == "shop":
                if bot["gold"]>200: bot["gold"]-=random.randint(50,200)
            elif action == "chat":
                chat_log.append({"time":now.isoformat(),"name":bot["display_name"],"channel":"world","msg":random.choice(CHAT_POOLS["world"]),"is_bot":True})
            bot["materials"]=mats
    
    # 更新战斗力
    for bot in data["bots"]:
        elv = bot.get("weapon_enhances",{}).get(bot.get("weapon_id","fire"),0)
        bot["combat_power"] = bot["level"]*200 + elv*35 + int(elv**1.25*12) + random.randint(500,3000)
    
    data["last_simulation_at"]=now.isoformat()
    save_bot_profiles(data)
    save_chat_log(chat_log[-200:])  # 保留最近200条
    save_announcements(announcements[-300:])
    return {"bots_updated":len(data["bots"]),"chat":len(chat_log),"announcements":len(announcements)}

def load_chat_log():
    ensure_bots_dir()
    if os.path.exists(BOT_CHAT_FILE):
        try:
            with open(BOT_CHAT_FILE,'r',encoding='utf-8') as f:return json.load(f)
        except:pass
    return []

def save_chat_log(log):
    ensure_bots_dir()
    with open(BOT_CHAT_FILE,'w',encoding='utf-8') as f:json.dump(log[-200:],f,ensure_ascii=False,indent=2)

def load_announcements():
    ensure_bots_dir()
    if os.path.exists(BOT_ANNOUNCE_FILE):
        try:
            with open(BOT_ANNOUNCE_FILE,'r',encoding='utf-8') as f:return json.load(f)
        except:pass
    return []

def save_announcements(data):
    ensure_bots_dir()
    with open(BOT_ANNOUNCE_FILE,'w',encoding='utf-8') as f:json.dump(data[-300:],f,ensure_ascii=False,indent=2)

def rp2(rel):
    """PyInstaller 资源路径"""
    return os.path.join(RESOURCE_DIR, rel)

PICTURE_DIR = rp2("picture")

# ─── 品质 ───
class Quality(Enum):
    COMMON=0; TRUE=1; EXTREME=2; DIVINE=3; LEGEND=4; MYTHIC=5
Q_COLORS = {0:"#cccccc",1:"#00ff66",2:"#0099ff",3:"#cc44ff",4:"#ff8800",5:"#ff4444"}
Q_TAGS  = {0:"⚪普通",1:"🟢真·",2:"🔵极·",3:"🟣神器·",4:"🟠传说·",5:"🔴神话·"}

# ─── 武器 (同前) ───
@dataclass
class Weapon:
    id:str;name:str;quality:Quality;base_damage:int;atk:int;defense:int;agility:int;luck:int
    angle:int;blast_radius:int;desc:str;price:int=0;level_req:int=1;hp_bonus:int=0;crit_dmg_bonus:float=0.0
    icon:str="";special_effect:str="";accuracy_bonus:float=0.0
    # ─── 新字段：武器定位系统 ───
    family:str=""          # 武器家族 (fire_cannon, thunder_cannon, railgun, etc.)
    weapon_type:str=""     # 武器类型定位 (sniper/standard/heavy/multi/control/dot)
    pit_radius:int=35      # 坑半径(px), 由类型决定非稀有度
    pit_depth:int=16       # 坑深度(px)
    pit_stack_limit:float=1.35  # 同位置连续炸坑扩大上限
    projectile_count:int=1 # 弹体数量(多段武器必须限制单段坑)

WEAPONS={
    "fire":Weapon("fire","烈火",Quality.COMMON,108,150,36,24,18,20,50,"高攻击，地面破坏小",80,1),
    "true_fire":Weapon("true_fire","真·烈火",Quality.TRUE,163,250,60,40,30,20,50,"攻击大幅提升",350,5,crit_dmg_bonus=0.05),
    "ext_fire":Weapon("ext_fire","极·烈火",Quality.EXTREME,272,275,66,44,33,20,50,"极致攻击力",800,12,crit_dmg_bonus=0.1),
    "god_fire":Weapon("god_fire","神·烈火焚天",Quality.DIVINE,445,320,75,50,40,25,55,"焚尽万物的神焰之炮",2000,20,crit_dmg_bonus=0.15),
    "boom":Weapon("boom","轰天",Quality.COMMON,108,24,150,18,36,55,70,"高防御，适合抛射",80,1,hp_bonus=30),
    "true_boom":Weapon("true_boom","真·轰天",Quality.TRUE,163,40,250,30,60,55,70,"防御极大幅提升",350,5,hp_bonus=60),
    "ext_boom":Weapon("ext_boom","极·轰天",Quality.EXTREME,272,44,275,33,66,55,70,"铜墙铁壁",800,12,hp_bonus=100),
    "god_boom":Weapon("god_boom","神·不灭轰天",Quality.DIVINE,445,50,320,38,75,60,75,"永不陷落的要塞之炮",2000,20,hp_bonus=150),
    "wind":Weapon("wind","神风",Quality.COMMON,108,36,18,150,24,15,50,"速度极快，先手优势",80,1),
    "true_wind":Weapon("true_wind","真·神风",Quality.TRUE,163,60,30,250,40,15,50,"疾风迅雷",350,5),
    "ext_wind":Weapon("ext_wind","极·神风",Quality.EXTREME,272,66,33,275,44,15,50,"快到看不清",800,12),
    "god_wind":Weapon("god_wind","神·风行者",Quality.DIVINE,445,75,38,320,50,20,55,"驾驭风暴的神速之炮",2000,20),
    "lightning":Weapon("lightning","雷霆",Quality.COMMON,108,18,24,36,150,20,55,"高幸运，暴击率高",80,1,crit_dmg_bonus=0.1),
    "true_lightning":Weapon("true_lightning","真·雷霆",Quality.TRUE,163,30,40,60,250,25,60,"幸运大幅提升",350,5,crit_dmg_bonus=0.15),
    "ext_lightning":Weapon("ext_lightning","极·雷霆",Quality.EXTREME,272,33,44,66,275,25,60,"暴击之王",800,12,crit_dmg_bonus=0.2),
    "god_lightning":Weapon("god_lightning","神·万钧雷霆",Quality.DIVINE,445,40,50,75,320,30,65,"召唤天雷的神罚之炮",2000,20,crit_dmg_bonus=0.3),
    "sima":Weapon("sima","司马砸缸",Quality.COMMON,108,180,130,30,40,20,65,"攻防兼备",100,1),
    "ext_sima":Weapon("ext_sima","极·司马砸缸",Quality.EXTREME,249,198,143,33,44,20,65,"完全体司马",600,10),
    "tv":Weapon("tv","黑白家电",Quality.COMMON,125,95,95,95,95,50,70,"四项全能",120,3),
    "ext_tv":Weapon("ext_tv","极·黑白家电",Quality.EXTREME,249,104,105,104,105,50,70,"完美均衡",650,10),
    "medkit":Weapon("medkit","医用工具箱",Quality.COMMON,108,130,30,180,40,15,60,"敏捷型",100,1),
    "ext_medkit":Weapon("ext_medkit","极·医用工具箱",Quality.EXTREME,249,143,33,198,44,15,60,"手术刀般精准",600,10),
    "plunger":Weapon("plunger","畅通利器",Quality.COMMON,117,40,180,30,130,30,65,"高防高运",90,2),
    "ext_plunger":Weapon("ext_plunger","极·畅通利器",Quality.EXTREME,249,44,188,33,143,30,65,"马桶塞终极形态",600,10),
    "fruit":Weapon("fruit","牛顿水果篮",Quality.COMMON,117,40,30,130,180,20,65,"高幸运高敏捷",90,2,crit_dmg_bonus=0.05),
    "ext_fruit":Weapon("ext_fruit","极·牛顿水果篮",Quality.EXTREME,249,44,33,143,198,20,65,"万有引力之篮",600,10,crit_dmg_bonus=0.1),
    "ancient_spear":Weapon("ancient_spear","远古竹枪",Quality.DIVINE,375,145,25,145,145,15,65,"远古流传的神秘竹枪",1500,15,crit_dmg_bonus=0.1),
    "minotaur":Weapon("minotaur","牛头怪",Quality.DIVINE,375,145,145,145,25,15,65,"牛头人战神的巨炮",1500,15,hp_bonus=80),
    "boomerang":Weapon("boomerang","爱心回力标",Quality.DIVINE,375,25,145,145,145,15,65,"爱之回力标",1500,15,hp_bonus=80),
    "legend_boom":Weapon("legend_boom","真·远古轰天",Quality.LEGEND,640,60,350,45,80,60,80,"轰天最终形态",3500,25,hp_bonus=200,crit_dmg_bonus=0.05),
    "legend_fire":Weapon("legend_fire","真·灭世烈火",Quality.LEGEND,640,350,60,50,45,25,60,"烈火最终形态",3500,25,crit_dmg_bonus=0.25),
    # ═══ 8把屌炸天副本武器 ═══
    "thunder_judge":Weapon("thunder_judge","雷霆审判炮",Quality.MYTHIC,729,200,80,60,100,20,55,"命中后追加电击⚡，造成30%额外伤害",0,20,crit_dmg_bonus=0.2,icon="⚡",special_effect="chain_lightning",accuracy_bonus=-0.08,family="thunder_cannon",weapon_type="heavy",pit_radius=58,pit_depth=28),
    "abyss_crossbow":Weapon("abyss_crossbow","深海龙息弩",Quality.MYTHIC,683,160,90,100,80,30,65,"命中后附加2回合「潮蚀」持续伤害🌊",0,18,hp_bonus=40,icon="🌊",special_effect="tide_erosion",family="abyss_cannon",weapon_type="dot",pit_radius=28,pit_depth=15),
    "blackhole_cannon":Weapon("blackhole_cannon","黑洞重力炮",Quality.MYTHIC,774,120,120,70,130,35,80,"命中点生成引力场🌀，拉扯敌人",0,22,hp_bonus=60,icon="🌀",special_effect="gravity_well",family="gravity_cannon",weapon_type="control",pit_radius=52,pit_depth=24),
    "seraphim_railgun":Weapon("seraphim_railgun","炽天使轨道炮",Quality.MYTHIC,843,280,40,50,60,10,40,"弹道极直·暴击追加光束✨ 坑极小",0,25,crit_dmg_bonus=0.35,icon="✨",special_effect="beam_strike",accuracy_bonus=0.2,family="railgun",weapon_type="sniper",pit_radius=20,pit_depth=10),
    "chaos_dice":Weapon("chaos_dice","混沌骰子发射器",Quality.MYTHIC,729,150,70,90,180,25,55,"随机触发燃烧🔥/冰冻❄️/暴击💥/回血💚",0,20,crit_dmg_bonus=0.15,icon="🎲",special_effect="random_chaos",family="chaos_cannon",weapon_type="standard",pit_radius=44,pit_depth=20),
    "mecha_fist":Weapon("mecha_fist","远古机甲拳套炮",Quality.LEGEND,518,250,60,40,50,15,50,"近距离伤害+40%·远距衰减-30%🤖",0,18,hp_bonus=50,icon="🤖",special_effect="close_combat",family="mecha_cannon",weapon_type="heavy",pit_radius=65,pit_depth=28),
    "eclipse_scythe":Weapon("eclipse_scythe","月蚀镰刃炮",Quality.MYTHIC,774,130,80,100,150,30,60,"伤害25%转化回血🌙·坑小续航强",0,22,hp_bonus=50,icon="🌙",special_effect="life_steal",family="vampire_cannon",weapon_type="dot",pit_radius=32,pit_depth=15),
    "godpunish_missile":Weapon("godpunish_missile","神罚多重导弹",Quality.MYTHIC,797,180,50,70,90,20,45,"一次3枚导弹🚀每枚45%伤害·单坑极小",0,23,crit_dmg_bonus=0.1,icon="🚀",special_effect="multi_missile",family="missile_cannon",weapon_type="multi",pit_radius=22,pit_depth=10,projectile_count=3),
    # ═══ 魔罐限定武器 ═══
    "true_minotaur":Weapon("true_minotaur","真·牛头怪",Quality.LEGEND,553,280,120,80,60,20,60,"近距命中追加冲撞伤害🐂·坑中等偏大",0,20,hp_bonus=80,icon="🐂",special_effect="charge_bonus",family="beast_cannon",weapon_type="heavy",pit_radius=60,pit_depth=28),
    "true_spear":Weapon("true_spear","真·远古竹枪",Quality.LEGEND,553,200,40,160,140,15,50,"弹道极稳·命中穿透护盾🎋·坑极小",0,20,crit_dmg_bonus=0.2,icon="🎋",special_effect="armor_pierce",family="ancient_cannon",weapon_type="sniper",pit_radius=22,pit_depth=10,accuracy_bonus=0.25),
    "true_boomerang":Weapon("true_boomerang","真·爱心回力标",Quality.LEGEND,553,150,100,120,130,25,55,"命中后回旋追加伤害💕·伤害25%转回血",0,20,hp_bonus=50,icon="💕",special_effect="boomerang_heal",family="love_cannon",weapon_type="control",pit_radius=40,pit_depth=18),
    "angel_gift":Weapon("angel_gift","真·天使之赐",Quality.LEGEND,588,120,140,100,160,30,60,"攻击后概率恢复生命🪽·获得护盾",0,22,hp_bonus=100,icon="🪽",special_effect="angel_heal",family="angel_cannon",weapon_type="dot",pit_radius=30,pit_depth=14),
}
# 非传说/神话武器(可在副本掉落)
DROPPABLE_WEAPONS = [wid for wid,w in WEAPONS.items() if w.quality not in (Quality.LEGEND,Quality.MYTHIC)]
# 神话武器掉落池
MYTHIC_DROPS = [wid for wid,w in WEAPONS.items() if w.quality==Quality.MYTHIC]
LEGEND_DROPS = [wid for wid,w in WEAPONS.items() if w.quality==Quality.LEGEND]

# ─── 装备系统 ───
class EquipSlot(Enum):
    HELMET="头盔"; CHEST="胸甲"; BOOTS="护腿"; ACCESSORY="饰品"

@dataclass
class Equipment:
    id:str;name:str;slot:EquipSlot;quality:Quality
    defense:int=0;hp_bonus:int=0;atk_bonus:int=0;agi_bonus:int=0;luk_bonus:int=0
    desc:str="";price:int=0;level_req:int=1
    special:str=""  # 特殊效果描述

EQUIPMENTS={
    # 头盔
    "cloth_hat":Equipment("cloth_hat","布帽",EquipSlot.HELMET,Quality.COMMON,defense=3,desc="普通布帽",price=50),
    "iron_helm":Equipment("iron_helm","铁盔",EquipSlot.HELMET,Quality.TRUE,defense=8,hp_bonus=20,desc="坚固的铁制头盔",price=200,level_req=5),
    "dragon_helm":Equipment("dragon_helm","龙角盔",EquipSlot.HELMET,Quality.EXTREME,defense=15,hp_bonus=50,atk_bonus=5,desc="龙角打造的神盔",price=600,level_req=12),
    "phoenix_crown":Equipment("phoenix_crown","凤凰冠",EquipSlot.HELMET,Quality.DIVINE,defense=22,hp_bonus=80,luk_bonus=10,desc="凤凰之力灌注的王冠",price=1500,level_req=18),
    # 胸甲
    "leather_vest":Equipment("leather_vest","皮背心",EquipSlot.CHEST,Quality.COMMON,defense=5,hp_bonus=15,desc="轻便皮甲",price=60),
    "chainmail":Equipment("chainmail","锁子甲",EquipSlot.CHEST,Quality.TRUE,defense=12,hp_bonus=40,desc="锁链护甲",price=250,level_req=5),
    "plate_armor":Equipment("plate_armor","板甲",EquipSlot.CHEST,Quality.EXTREME,defense=20,hp_bonus=80,desc="厚重的钢板护甲",price=700,level_req=12),
    "dragon_chest":Equipment("dragon_chest","龙鳞胸甲",EquipSlot.CHEST,Quality.DIVINE,defense=30,hp_bonus=150,luk_bonus=5,desc="龙鳞编织的神甲",price=1800,level_req=18),
    # 护腿
    "cloth_pants":Equipment("cloth_pants","布裤",EquipSlot.BOOTS,Quality.COMMON,defense=2,agi_bonus=3,desc="普通布裤",price=40),
    "leather_boots":Equipment("leather_boots","皮靴",EquipSlot.BOOTS,Quality.TRUE,defense=6,agi_bonus=8,desc="轻便皮靴",price=180,level_req=4),
    "wind_boots":Equipment("wind_boots","疾风靴",EquipSlot.BOOTS,Quality.EXTREME,defense=10,agi_bonus=18,desc="乘风而行",price=500,level_req=10),
    "shadow_boots":Equipment("shadow_boots","暗影靴",EquipSlot.BOOTS,Quality.DIVINE,defense=16,agi_bonus=30,luk_bonus=8,desc="行于暗影之中",price=1200,level_req=16),
    # 饰品
    "wood_ring":Equipment("wood_ring","木戒指",EquipSlot.ACCESSORY,Quality.COMMON,luk_bonus=3,desc="朴素的木戒指",price=45),
    "silver_ring":Equipment("silver_ring","银戒指",EquipSlot.ACCESSORY,Quality.TRUE,atk_bonus=5,luk_bonus=5,desc="闪亮的银戒指",price=220,level_req=5),
    "ruby_amulet":Equipment("ruby_amulet","红宝石项链",EquipSlot.ACCESSORY,Quality.EXTREME,atk_bonus=10,hp_bonus=40,luk_bonus=8,desc="蕴含魔力的宝石",price=650,level_req=10),
    "star_pendant":Equipment("star_pendant","星辰吊坠",EquipSlot.ACCESSORY,Quality.DIVINE,atk_bonus=15,hp_bonus=70,luk_bonus=15,desc="星辰之力的吊坠",price=1500,level_req=16),
    # ═══ 金色/传说装备 ═══
    "golden_crown":Equipment("golden_crown","黄金王冠",EquipSlot.HELMET,Quality.LEGEND,defense=28,hp_bonus=120,atk_bonus=8,luk_bonus=12,desc="金光璀璨的传说王冠",price=3000,level_req=25),
    "golden_plate":Equipment("golden_plate","黄金圣甲",EquipSlot.CHEST,Quality.LEGEND,defense=38,hp_bonus=200,atk_bonus=5,luk_bonus=8,desc="传说级黄金打造的圣甲",price=3500,level_req=25),
    "golden_boots":Equipment("golden_boots","黄金战靴",EquipSlot.BOOTS,Quality.LEGEND,defense=20,agi_bonus=40,luk_bonus=10,desc="踏风而行的传说战靴",price=2500,level_req=22),
    "golden_pendant":Equipment("golden_pendant","黄金神坠",EquipSlot.ACCESSORY,Quality.LEGEND,atk_bonus=20,hp_bonus=100,luk_bonus=18,desc="传说级星辰神坠",price=3000,level_req=22),
}
# 可掉落装备(非传说)
DROPPABLE_EQUIP = [eid for eid,e in EQUIPMENTS.items() if e.quality!=Quality.LEGEND]

# ═══ 统一爆率配置 RATE_CONFIG ═══
RATE_CONFIG = {
    # 人机练习掉落 (按玩家等级段)
    "pve_drops": {
        "1-9":   {"common_frag":0.35,"green_frag":0.12,"blue_frag":0.02,"purple_frag":0,"gold_frag":0},
        "10-19": {"common_frag":0.28,"green_frag":0.18,"blue_frag":0.05,"purple_frag":0,"gold_frag":0},
        "20-29": {"common_frag":0.20,"green_frag":0.22,"blue_frag":0.08,"purple_frag":0.01,"gold_frag":0},
        "30-39": {"common_frag":0.12,"green_frag":0.24,"blue_frag":0.12,"purple_frag":0.02,"gold_frag":0},
        "40+":   {"common_frag":0,"green_frag":0.20,"blue_frag":0.15,"purple_frag":0.04,"gold_frag":0.01},
    },
    # 真人对战奖励系数 (相对于同级副本)
    "bot_pvp_win":  {"coins_ratio":0.70,"exp_ratio":0.50,"arena_coins":(10,20)},
    "bot_pvp_lose": {"coins_ratio":0.21,"exp_ratio":0.15,"arena_coins":(3,6)},
}

def get_pve_rate_config(player_level):
    """根据玩家等级返回人机掉落概率"""
    if player_level <= 9: return RATE_CONFIG["pve_drops"]["1-9"]
    if player_level <= 19: return RATE_CONFIG["pve_drops"]["10-19"]
    if player_level <= 29: return RATE_CONFIG["pve_drops"]["20-29"]
    if player_level <= 39: return RATE_CONFIG["pve_drops"]["30-39"]
    return RATE_CONFIG["pve_drops"]["40+"]

# ═══ 魔罐奖励池 ═══
ANGEL_CAN_POOLS = {
    "angel": {"common":0.50,"rare":0.30,"epic":0.13,"legend":0.05,"mythic":0.02},
    "silver": {"common":0.35,"rare":0.30,"epic":0.20,"legend":0.10,"mythic":0.05},
    "gold":   {"common":0.20,"rare":0.25,"epic":0.25,"legend":0.18,"mythic":0.12},
}
# 魔罐限定武器ID(副本不掉落)
POT_EXCLUSIVE_WEAPONS = ["true_minotaur","true_spear","true_boomerang","angel_gift"]
# 魔罐奖励-武器池
POT_WEAPON_POOLS = {
    "common": ["fire","boom","wind","lightning","sima","tv","medkit","plunger","fruit"],
    "rare":   ["true_fire","true_boom","true_wind","true_lightning"],
    "epic":   ["ext_fire","ext_boom","ext_wind","ext_lightning","ext_sima","ext_tv"],
    "legend": POT_EXCLUSIVE_WEAPONS + ["god_fire","god_boom","god_wind","god_lightning"],
    "mythic": POT_EXCLUSIVE_WEAPONS,
}
POT_EQUIP_POOLS = {
    "common": ["cloth_hat","leather_vest","cloth_pants","wood_ring"],
    "rare":   ["iron_helm","leather_boots","silver_ring"],
    "epic":   ["dragon_helm","plate_armor","wind_boots","ruby_amulet"],
    "legend": ["phoenix_crown","dragon_chest","shadow_boots","star_pendant"],
}
POT_MATERIAL_POOLS = {
    "common": [{"type":"coins","name":"金币","n":(50,200)},{"type":"stone","tier":"small","name":"小强化石","n":(1,3)},{"type":"equip_fragments","name":"装备碎片","n":(2,5)}],
    "rare":   [{"type":"stone","tier":"medium","name":"中强化石","n":(1,2)},{"type":"stone","tier":"large","name":"大强化石","n":1},{"type":"weapon_fragments","name":"武器碎片","n":(3,7)}],
    "epic":   [{"type":"stone","tier":"large","name":"大强化石","n":(2,4)},{"type":"fragment","name":"魔罐碎片","n":(5,15)},{"type":"weapon_fragments","name":"武器碎片","n":(8,16)},{"type":"equip_fragments","name":"装备碎片","n":(8,16)}],
    "legend": [{"type":"blessing","name":"天使祝福石","n":1},{"type":"fragment","name":"魔罐碎片","n":(20,50)},{"type":"weapon_fragments","name":"武器碎片","n":(18,35)},{"type":"equip_fragments","name":"装备碎片","n":(18,35)}],
    "mythic": [{"type":"blessing","name":"天使祝福石","n":(2,3)},{"type":"fragment","name":"魔罐碎片","n":(50,100)},{"type":"weapon_fragments","name":"武器碎片","n":(40,75)},{"type":"equip_fragments","name":"装备碎片","n":(40,75)}],
}

def roll_angel_can(can_type):
    """开启魔罐,返回奖励列表"""
    pool = ANGEL_CAN_POOLS.get(can_type, ANGEL_CAN_POOLS["angel"])
    rarity = random.choices(["common","rare","epic","legend","mythic"],
        weights=[pool["common"],pool["rare"],pool["epic"],pool["legend"],pool["mythic"]],k=1)[0]
    rewards = []
    # 武器
    if random.random() < 0.4:
        wpool = POT_WEAPON_POOLS.get(rarity, POT_WEAPON_POOLS["common"])
        wid = random.choice(wpool)
        if wid in WEAPONS:
            w = WEAPONS[wid]
            rewards.append({"type":"weapon","id":wid,"name":w.name,"quality":w.quality.value,"quality_tag":Q_TAGS[w.quality.value],"icon":w.icon,"rarity":rarity,"is_pot_exclusive":wid in POT_EXCLUSIVE_WEAPONS})
    # 装备
    if random.random() < 0.3:
        epool = POT_EQUIP_POOLS.get(rarity, POT_EQUIP_POOLS["common"])
        eid = random.choice(epool)
        if eid in EQUIPMENTS:
            eq = EQUIPMENTS[eid]
            rewards.append({"type":"equip","id":eid,"name":eq.name,"slot":eq.slot.value,"quality":eq.quality.value,"quality_tag":Q_TAGS[eq.quality.value],"rarity":rarity})
    # 材料(必给)
    mpool = POT_MATERIAL_POOLS.get(rarity, POT_MATERIAL_POOLS["common"])
    mat = random.choice(mpool)
    if mat["type"] == "coins":
        rewards.append({"type":"coins","name":"金币","n":random.randint(*mat["n"]),"rarity":"common"})
    elif mat["type"] == "stone":
        rewards.append({"type":"stone","tier":mat["tier"],"name":mat["name"],"n":mat["n"] if isinstance(mat["n"],int) else random.randint(*mat["n"]),"rarity":"common"})
    elif mat["type"] == "fragment":
        rewards.append({"type":"fragment","name":mat["name"],"n":mat["n"] if isinstance(mat["n"],int) else random.randint(*mat["n"]),"rarity":"common"})
    elif mat["type"] in ("weapon_fragments","equip_fragments"):
        n = mat["n"] if isinstance(mat["n"],int) else random.randint(*mat["n"])
        if mat["type"] == "weapon_fragments":
            # 随机选一个神器/传说/神话武器
            pool = [wid for wid,w in WEAPONS.items() if w.quality.value > SHOP_MAX_WEAPON_QUALITY.value]
            if pool:
                wid = random.choice(pool)
                w = WEAPONS[wid]
                rewards.append({"type":"weapon_fragments","name":f"{w.icon} {w.name}·碎片","frag_id":wid,"n":n,"rarity":"common"})
        else:
            pool = [eid for eid,e in EQUIPMENTS.items() if e.quality.value > SHOP_MAX_EQUIP_QUALITY.value]
            if pool:
                eid = random.choice(pool)
                e = EQUIPMENTS[eid]
                rewards.append({"type":"equip_fragments","name":f"🛡️ {e.name}·碎片","frag_id":eid,"n":n,"rarity":"common"})
    elif mat["type"] == "blessing":
        rewards.append({"type":"blessing","name":mat["name"],"n":mat["n"] if isinstance(mat["n"],int) else 1,"rarity":"common"})
    return rewards, rarity

# ─── 强化公式系统 ───
ENHANCE_STONE_TIERS={"small":"小强化石","medium":"中强化石","large":"大强化石"}
MAX_WEAPON_ENHANCE = 40      # 武器最高+40
MAX_EQUIP_ENHANCE = 40       # 装备最高+40
MIN_ENHANCE_RATE = 50        # 强化保底50%

def calculate_enhance_rate(level, stones, luck):
    """强化成功率: lv0-29递减2.5%/级, lv30-39递减3%/级, 最小50%"""
    if level >= MAX_WEAPON_ENHANCE: return 0, 0, 0  # 已满级
    if level < 30:
        lf = max(0.15, 1.0 - level * 0.025)  # 旧公式
    else:
        lf = max(0.08, 1.0 - 30*0.025 - (level-29)*0.03)  # 30级后递减3%
    raw = (stones.get("small",0)*12 + stones.get("medium",0)*30 + stones.get("large",0)*70 
           + stones.get("super",0)*150 + stones.get("angel_blessing",0)*50)
    luck_b = min(20, luck // 10)
    rate = round(min(95, raw * lf + luck_b), 2)
    return max(MIN_ENHANCE_RATE, rate), lf, raw  # 保底50%

def enhance_gold_cost(level):
    if level < 30:
        return 100 + level*60 + int((level**1.5)*20)
    else:
        return 5000 + (level-29)*2000 + int((level**1.8)*30)  # 30级后更贵

# ─── 弹道力度表 ───
_65_P=[13,21,26,31.5,37,41,44,48.5,53,56,58,61,64,67,70,73,76,79,82,85]
_50_P=[14.1,20.1,24.8,28,32.5,35.9,39.0,42.0,44.9,48.3,50.5,53,55.5,58,60.5,63.0,65.5,68.0,70.0,72.5]
_30_P=[14,20,24.7,28.7,32.3,35.7,38.8,41.8,44.7,47.5,50.2,52.8,55.3,57.9,60.3,62.7,65.7,67.5,69.8,72.1]

# ─── Capoo 敌人系统 ───
# 扫描 enemy 目录
ENEMY_DIR = os.path.join(PICTURE_DIR, "enemy")
KIWI_DIR = os.path.join(PICTURE_DIR, "kiwi")

def scan_gifs(directory):
    """扫描目录下所有gif"""
    if not os.path.exists(directory): return []
    gifs=glob.glob(os.path.join(directory,"*.gif"))
    return [os.path.basename(g) for g in gifs]

CAPOO_GIFS = []
KIWI_GIFS = []
_gifs_scanned = False

def ensure_gifs():
    global CAPOO_GIFS, KIWI_GIFS, _gifs_scanned
    # 如果列表为空或未扫描，重新扫描
    if _gifs_scanned and CAPOO_GIFS and KIWI_GIFS:
        return
    ed = os.path.join(rp2("picture"), "enemy")
    kd = os.path.join(rp2("picture"), "kiwi")
    if os.path.exists(ed):
        gfs = [os.path.basename(g) for g in glob.glob(os.path.join(ed,"*.gif"))]
        if gfs: CAPOO_GIFS[:] = gfs
    if os.path.exists(kd):
        gfs = [os.path.basename(g) for g in glob.glob(os.path.join(kd,"*.gif"))]
        if gfs: KIWI_GIFS[:] = gfs
    _gifs_scanned = True

# Capoo 名字池
CAPOO_NAMES=[
    "暴怒卡波","贪睡卡波","贪吃卡波","害羞卡波","傲娇卡波",
    "战斗卡波","魔法卡波","忍者卡波","海盗卡波","骑士卡波",
    "暗影卡波","烈焰卡波","冰霜卡波","雷电卡波","星辰卡波",
    "捣蛋卡波","懒惰卡波","好奇卡波","勇敢卡波","胆小卡波",
    "天使卡波","恶魔卡波","机械卡波","幽灵卡波","彩虹卡波",
]

# Capoo 台词库
CAPOO_LINES={
    "enter":["喵嗷！来战吧！","卡波卡波！","哼，看我的厉害！","你打不过我的喵~","来了个新对手呢！","今天手感不错喵！"],
    "attack":["吃我一炮！","喵嗷——！","卡波冲击！","命中吧！","看招！","尝尝这个！"],
    "hit":["好痛喵！","可恶…","哼，就这？","有点疼呢…","喵！！"],
    "crit":["哇啊啊啊好痛！！","喵嗷嗷嗷！！","太过分了喵！"],
    "defeat":["我输了喵…","卡波认输了…","下次一定赢！","你变强了呢…"],
    "victory":["太弱了喵~","卡波大胜利！","这就是实力的差距！","回去再练练吧！"],
    "idle":["卡波卡波~","今天天气不错喵","肚子饿了…","想睡觉喵…"],
}
# 简化副本台词
KIWI_LINES={
    "enter":["叽叽！","kiwi——！","叽叽叽叽！","咕咕！"],
    "attack":["叽！！","kiwi攻击！","冲刺！叽！","啄你！"],
    "hit":["叽…","好痛叽！","呜叽！"],
    "defeat":["叽叽…输了…","kiwi倒下了…"],
    "victory":["kiwi赢了叽！","叽叽叽！"],
}

# 根据gif文件名映射capoo属性
def capoo_stats(gif_name):
    """根据gif名给capoo分配属性倾向"""
    h=hash(gif_name)%5
    if h==0: return {"倾向":"攻击型","atk_m":1.3,"def_m":0.8,"agi_m":1.0,"luk_m":0.9}
    elif h==1: return {"倾向":"防御型","atk_m":0.8,"def_m":1.3,"agi_m":0.9,"luk_m":1.0}
    elif h==2: return {"倾向":"敏捷型","atk_m":0.9,"def_m":0.8,"agi_m":1.3,"luk_m":1.0}
    elif h==3: return {"倾向":"幸运型","atk_m":1.0,"def_m":0.9,"agi_m":0.9,"luk_m":1.3}
    else: return {"倾向":"均衡型","atk_m":1.05,"def_m":1.05,"agi_m":1.05,"luk_m":1.05}

# Kiwi难度分级
KIWI_DIFFICULTY={
    "easy":   {"前缀":"小","后缀":"雏鸟","atk_m":0.7,"def_m":0.7,"agi_m":0.8,"luk_m":0.7},
    "normal": {"前缀":"成年","后缀":"几维","atk_m":1.0,"def_m":1.0,"agi_m":1.0,"luk_m":1.0},
    "hard":   {"前缀":"精英","后缀":"战士","atk_m":1.3,"def_m":1.2,"agi_m":1.2,"luk_m":1.2},
    "boss":   {"前缀":"巨型","后缀":"王","atk_m":1.8,"def_m":1.6,"agi_m":1.3,"luk_m":1.5},
}

DUNGEONS = [
    {"id":"goblin_cave","name":"几维鸟草窝","lv":1,"desc":"新手几维鸟在草窝里守着第一批补给",
     "stages":[{"name":"草窝入口","n":2,"d":"normal"},{"name":"暗羽鸟巢","n":1,"d":"normal","boss":True}],
     "rw":{"coins":(120,250),"exp":(100,200),"stone":"small","stone_n":(1,3)},
     "drops":[
         {"type":"weapon","ids":["fire","boom","wind","lightning","sima","medkit","plunger","fruit"],"rate":0.15,"label":"普通武器"},
         {"type":"weapon","ids":["true_fire","true_boom","true_wind","true_lightning"],"rate":0.05,"label":"真·武器"},
         {"type":"equip","ids":["cloth_hat","leather_vest","cloth_pants","wood_ring"],"rate":0.20,"label":"普通装备"},
     ]},
    {"id":"dark_forest","name":"夜羽灌木林","lv":5,"desc":"夜色里的几维鸟会从灌木间突然冲刺",
     "stages":[{"name":"灌木边缘","n":2,"d":"normal"},{"name":"夜羽迷雾","n":2,"d":"normal"},{"name":"古树鸟巢","n":1,"d":"hard","boss":True}],
     "rw":{"coins":(300,550),"exp":(250,450),"stone":"small","stone_n":(2,5)},
     "drops":[
         {"type":"weapon","ids":["fire","boom","wind","lightning","sima","tv","medkit","plunger","fruit"],"rate":0.18,"label":"普通武器"},
         {"type":"weapon","ids":["true_fire","true_boom","true_wind","true_lightning"],"rate":0.08,"label":"真·武器"},
         {"type":"equip","ids":["iron_helm","leather_boots","silver_ring"],"rate":0.15,"label":"真·装备"},
     ]},
    {"id":"dragon_peak","name":"红喙火山坡","lv":10,"desc":"红喙几维鸟在滚烫山坡上训练爆发力",
     "stages":[{"name":"火山营地","n":2,"d":"normal"},{"name":"热风山脊","n":2,"d":"hard"},{"name":"红喙巢穴","n":1,"d":"hard","boss":True}],
     "rw":{"coins":(550,1000),"exp":(450,800),"stone":"medium","stone_n":(1,3)},
     "drops":[
         {"type":"weapon","ids":["ext_fire","ext_boom","ext_wind","ext_lightning","ext_sima","ext_tv","ext_medkit","ext_plunger","ext_fruit"],"rate":0.12,"label":"极·武器"},
         {"type":"weapon","ids":["ancient_spear","minotaur","boomerang"],"rate":0.04,"label":"神器武器(3%)"},
         {"type":"equip","ids":["dragon_helm","plate_armor","wind_boots","ruby_amulet"],"rate":0.15,"label":"极·装备"},
     ]},
    {"id":"abyss","name":"黑羽深谷","lv":15,"desc":"黑羽几维鸟把稀有碎片藏在深谷裂缝里",
     "stages":[{"name":"深谷入口","n":2,"d":"hard"},{"name":"熔岩羽道","n":3,"d":"hard"},{"name":"黑羽王座","n":1,"d":"hard","boss":True}],
     "rw":{"coins":(1000,2000),"exp":(700,1300),"stone":"large","stone_n":(1,2)},
     "drops":[
         {"type":"weapon","ids":["ext_fire","ext_boom","ext_wind","ext_lightning","god_fire","god_boom","god_wind","god_lightning"],"rate":0.15,"label":"极·/神器武器"},
         {"type":"weapon","ids":["mecha_fist"],"rate":0.03,"label":"🤖远古机甲拳套炮(3%)"},
         {"type":"weapon","ids":["legend_boom","legend_fire"],"rate":0.02,"label":"传说武器(1.5%)"},
         {"type":"equip","ids":["phoenix_crown","dragon_chest","shadow_boots","star_pendant"],"rate":0.12,"label":"神器装备"},
     ]},
    # ═══ 新副本(神话武器专属) ═══
    {"id":"thunder_lab","name":"雷羽鸟场","lv":20,"desc":"雷羽几维鸟栖息在闪电高塔，雷霆审判炮的铸造之地",
     "stages":[{"name":"高压鸟道","n":2,"d":"hard"},{"name":"电磁羽暴","n":2,"d":"hard"},{"name":"雷羽核心","n":1,"d":"hard","boss":True}],
     "rw":{"coins":(1500,2800),"exp":(800,1500),"stone":"large","stone_n":(2,4)},
     "drops":[
         {"type":"weapon","ids":["thunder_judge"],"rate":0.008,"label":"🔴雷霆审判炮(0.8%神话)"},
         {"type":"weapon","ids":["god_fire","god_boom","god_wind","god_lightning"],"rate":0.10,"label":"神器武器(10%)"},
         {"type":"weapon","ids":["ext_fire","ext_boom","ext_wind","ext_lightning"],"rate":0.20,"label":"极·武器(20%)"},
     ]},
    {"id":"abyss_ruins","name":"蓝羽潮汐礁","lv":22,"desc":"蓝羽几维鸟守着潮汐礁，深海龙息弩的沉睡之所",
     "stages":[{"name":"珊瑚鸟路","n":2,"d":"hard"},{"name":"潮汐裂口","n":2,"d":"hard"},{"name":"蓝羽祭坛","n":1,"d":"hard","boss":True}],
     "rw":{"coins":(1600,3000),"exp":(900,1600),"stone":"large","stone_n":(2,4)},
     "drops":[
         {"type":"weapon","ids":["abyss_crossbow"],"rate":0.008,"label":"🔴深海龙息弩(0.8%神话)"},
         {"type":"weapon","ids":["god_fire","god_boom","god_wind","god_lightning"],"rate":0.10,"label":"神器武器(10%)"},
         {"type":"weapon","ids":["ext_fire","ext_boom","ext_wind","ext_lightning"],"rate":0.20,"label":"极·武器(20%)"},
     ]},
    {"id":"star_rift","name":"星羽陨坑","lv":24,"desc":"星羽几维鸟在陨坑中盘旋，黑洞重力炮在此凝聚",
     "stages":[{"name":"流星羽雨","n":2,"d":"hard"},{"name":"引力鸟巢","n":2,"d":"hard"},{"name":"星羽核心","n":1,"d":"hard","boss":True}],
     "rw":{"coins":(1800,3500),"exp":(1000,1800),"stone":"large","stone_n":(3,5)},
     "drops":[
         {"type":"weapon","ids":["blackhole_cannon"],"rate":0.007,"label":"🔴黑洞重力炮(0.7%神话)"},
         {"type":"weapon","ids":["god_fire","god_boom","god_wind","god_lightning"],"rate":0.10,"label":"神器武器(10%)"},
     ]},
    {"id":"sky_sanctuary","name":"白羽云巢","lv":25,"desc":"白羽几维鸟守护云端巢穴，炽天使轨道炮的守护之地",
     "stages":[{"name":"云海鸟阶","n":2,"d":"hard"},{"name":"白羽回廊","n":2,"d":"hard"},{"name":"云巢王座","n":1,"d":"hard","boss":True}],
     "rw":{"coins":(2000,4000),"exp":(1200,2000),"stone":"large","stone_n":(3,5)},
     "drops":[
         {"type":"weapon","ids":["seraphim_railgun"],"rate":0.006,"label":"🔴炽天使轨道炮(0.6%神话)"},
         {"type":"weapon","ids":["god_fire","god_boom","god_wind","god_lightning"],"rate":0.10,"label":"神器武器(10%)"},
     ]},
    {"id":"chaos_playground","name":"彩羽迷彩乐园","lv":26,"desc":"彩羽几维鸟爱把碎片藏进随机机关，混沌骰子发射器的诞生地",
     "stages":[{"name":"骰子鸟厅","n":2,"d":"hard"},{"name":"卡牌羽廊","n":2,"d":"hard"},{"name":"彩羽轮盘","n":1,"d":"hard","boss":True}],
     "rw":{"coins":(2200,4500),"exp":(1500,2500),"stone":"large","stone_n":(3,6)},
     "drops":[
         {"type":"weapon","ids":["chaos_dice"],"rate":0.007,"label":"🔴混沌骰子发射器(0.7%神话)"},
         {"type":"weapon","ids":["god_fire","god_boom","god_wind","god_lightning"],"rate":0.10,"label":"神器武器(10%)"},
     ]},
    {"id":"moon_temple","name":"月羽静谧园","lv":28,"desc":"月羽几维鸟只在夜色里现身，月蚀镰刃炮的低语回响",
     "stages":[{"name":"月光羽庭","n":2,"d":"hard"},{"name":"暗影鸟廊","n":3,"d":"hard"},{"name":"月羽之座","n":1,"d":"hard","boss":True}],
     "rw":{"coins":(2500,5000),"exp":(1800,3000),"stone":"large","stone_n":(4,6)},
     "drops":[
         {"type":"weapon","ids":["eclipse_scythe"],"rate":0.006,"label":"🔴月蚀镰刃炮(0.6%神话)"},
         {"type":"weapon","ids":["god_fire","god_boom","god_wind","god_lightning"],"rate":0.10,"label":"神器武器(10%)"},
     ]},
    {"id":"doomsday_factory","name":"钢羽终焉巢","lv":30,"desc":"钢羽几维鸟把终极零件藏进机械巢，神罚多重导弹的最终试炼",
     "stages":[{"name":"钢羽装配线","n":3,"d":"hard"},{"name":"导弹羽仓","n":2,"d":"hard"},{"name":"终焉鸟巢","n":1,"d":"hard","boss":True}],
     "rw":{"coins":(3000,6000),"exp":(2000,4000),"stone":"large","stone_n":(5,8)},
     "drops":[
         {"type":"weapon","ids":["godpunish_missile"],"rate":0.005,"label":"🔴神罚多重导弹(0.5%神话)"},
         {"type":"weapon","ids":["legend_boom","legend_fire"],"rate":0.02,"label":"传说武器(1.5%)"},
         {"type":"weapon","ids":["god_fire","god_boom","god_wind","god_lightning"],"rate":0.10,"label":"神器武器(10%)"},
     ]},
    # ═══ 40+ 高级副本(碎片掉落为主) ═══
    {"id":"dragon_grave","name":"龙骸荒原","lv":40,"desc":"远古龙骸散落荒原，高阶碎片在此凝聚",
     "stages":[{"name":"龙骨入口","n":2,"d":"hard"},{"name":"龙息裂谷","n":3,"d":"hard"},{"name":"龙骸王座","n":1,"d":"hard","boss":True}],
     "rw":{"coins":(3000,6000),"exp":(2000,3500),"stone":"large","stone_n":(3,6)},
     "drops":[
         {"type":"weapon","ids":["god_fire","god_boom","god_wind","god_lightning"],"rate":0.15,"label":"神器武器(15%)"},
         {"type":"weapon","ids":["thunder_judge","abyss_crossbow","blackhole_cannon","seraphim_railgun"],"rate":0.03,"label":"神话武器(3%)"},
         {"type":"equip","ids":["phoenix_crown","dragon_chest","shadow_boots","star_pendant"],"rate":0.15,"label":"神器装备"},
     ]},
    {"id":"phoenix_peak","name":"凤羽天阶","lv":45,"desc":"凤羽几维鸟涅槃之地，传说碎片如雨般散落",
     "stages":[{"name":"天阶入口","n":2,"d":"hard"},{"name":"凤羽回廊","n":3,"d":"hard"},{"name":"涅槃祭坛","n":1,"d":"hard","boss":True}],
     "rw":{"coins":(4000,8000),"exp":(3000,5000),"stone":"large","stone_n":(4,8)},
     "drops":[
         {"type":"weapon","ids":["god_fire","god_boom","god_wind","god_lightning","legend_boom","legend_fire"],"rate":0.18,"label":"传说/神器武器(18%)"},
         {"type":"weapon","ids":["chaos_dice","mecha_fist","eclipse_scythe","godpunish_missile"],"rate":0.04,"label":"神话武器(4%)"},
         {"type":"equip","ids":["phoenix_crown","dragon_chest","shadow_boots","star_pendant"],"rate":0.20,"label":"神器装备(20%)"},
     ]},
    {"id":"godfall_abyss","name":"神陨深渊","lv":50,"desc":"众神陨落之地，最强神话武器与海量碎片等待勇者",
     "stages":[{"name":"深渊边缘","n":2,"d":"hard"},{"name":"神骸走廊","n":3,"d":"hard"},{"name":"神陨核心","n":1,"d":"hard","boss":True}],
     "rw":{"coins":(5000,12000),"exp":(4000,7000),"stone":"large","stone_n":(5,10)},
     "drops":[
         {"type":"weapon","ids":["thunder_judge","abyss_crossbow","blackhole_cannon","seraphim_railgun","chaos_dice","mecha_fist","eclipse_scythe","godpunish_missile"],"rate":0.06,"label":"神话武器(6%)"},
         {"type":"weapon","ids":["legend_boom","legend_fire","god_fire","god_boom","god_wind","god_lightning"],"rate":0.22,"label":"传说/神器武器(22%)"},
         {"type":"equip","ids":["phoenix_crown","dragon_chest","shadow_boots","star_pendant"],"rate":0.25,"label":"神器装备(25%)"},
     ]},
]

# ═══════════════════ 角色类 ═══════════════════
MAX_PLAYER_LEVEL = 100
SHOP_MAX_WEAPON_QUALITY = Quality.EXTREME
SHOP_MAX_EQUIP_QUALITY = Quality.EXTREME

def shop_price(item):
    """金币商店价格：真·10倍，极·100倍；神器及以上不进入金币商店。"""
    if item.quality == Quality.TRUE:
        return item.price * 10
    if item.quality == Quality.EXTREME:
        return item.price * 100
    return item.price

def fragment_need_for_quality(q):
    """所有武器/装备统一需要70个相同碎片兑换"""
    return 70

PVP_DIFFICULTIES = [
    {"id":"d1","name":"青铜练习场","cp_req":500,"scale":0.72,"coins":(60,120),"exp":(35,70),"frag":(0,1)},
    {"id":"d2","name":"白银练习场","cp_req":1200,"scale":0.86,"coins":(90,170),"exp":(55,95),"frag":(0,2)},
    {"id":"d3","name":"黄金练习场","cp_req":2500,"scale":1.00,"coins":(130,230),"exp":(80,130),"frag":(1,3)},
    {"id":"d4","name":"铂金练习场","cp_req":4500,"scale":1.18,"coins":(180,300),"exp":(110,170),"frag":(2,5)},
    {"id":"d5","name":"钻石练习场","cp_req":7000,"scale":1.38,"coins":(240,390),"exp":(150,230),"frag":(4,8)},
    {"id":"d6","name":"大师试炼场","cp_req":10000,"scale":1.62,"coins":(330,520),"exp":(210,320),"frag":(6,12)},
    {"id":"d7","name":"宗师试炼场","cp_req":14000,"scale":1.92,"coins":(450,700),"exp":(290,430),"frag":(9,18)},
    {"id":"d8","name":"王者试炼场","cp_req":18000,"scale":2.28,"coins":(620,960),"exp":(420,620),"frag":(14,26)},
    {"id":"d9","name":"传说试炼场","cp_req":21000,"scale":2.72,"coins":(850,1300),"exp":(650,950),"frag":(18,34)},
    {"id":"d10","name":"神话试炼场","cp_req":24000,"scale":3.25,"coins":(1200,1900),"exp":(900,1400),"frag":(24,45)},
]
PVP_DIFF_MAP = {d["id"]:d for d in PVP_DIFFICULTIES}
PVP_LEGACY_MAP = {"easy":"d1","normal":"d3","hard":"d5"}

def get_pvp_diff(diff_id):
    return PVP_DIFF_MAP.get(PVP_LEGACY_MAP.get(diff_id,diff_id), PVP_DIFFICULTIES[0])

def grant_varied_rewards(p, profile, source="pve", victory=True):
    if not victory:
        coins=random.randint(15,45); exp=random.randint(8,25); frags=0
        p.coins+=coins; p.gain_exp(exp)
        return {"coins":coins,"exp":exp,"magic_can_fragment":frags,"items":[]}
    coins=random.randint(*profile.get("coins",(60,120)))
    exp=random.randint(*profile.get("exp",(35,70)))
    frags=random.randint(*profile.get("frag",(0,1)))
    p.coins+=coins
    leveled=p.gain_exp(exp)
    items=[]
    if frags:
        p.magic_can_fragment+=frags
        items.append({"type":"fragment","name":"魔罐碎片","n":frags})
    if random.random()<profile.get("hammer_rate",0.25):
        h=random.randint(1,3);p.angel_hammer+=h;items.append({"type":"angel_hammer","name":"天使魔锤","n":h})
    if random.random()<profile.get("pot_rate",0):
        p.angel_pot+=1;items.append({"type":"angel_pot","name":"天使魔罐","n":1})
    if random.random()<profile.get("stone_rate",0.35):
        tier=random.choice(["small","medium","large"] if profile.get("scale",1)>1.8 else ["small","medium"])
        n=random.randint(1,3);p.add_stone(tier,n);items.append({"type":"stone","name":ENHANCE_STONE_TIERS[tier],"tier":tier,"n":n})
    if random.random()<profile.get("weapon_frag_rate",0.25):
        n=random.randint(2,8)
        pool=[wid for wid,w in WEAPONS.items() if w.quality.value>SHOP_MAX_WEAPON_QUALITY.value]
        if pool:
            wid=random.choice(pool);w=WEAPONS[wid]
            p.weapon_fragments[wid]=p.weapon_fragments.get(wid,0)+n
            items.append({"type":"weapon_fragments","name":f"{w.icon} {w.name}·碎片","frag_id":wid,"n":n})
    if random.random()<profile.get("equip_frag_rate",0.22):
        n=random.randint(2,8)
        pool=[eid for eid,e in EQUIPMENTS.items() if e.quality.value>SHOP_MAX_EQUIP_QUALITY.value]
        if pool:
            eid=random.choice(pool);e=EQUIPMENTS[eid]
            p.equip_fragments[eid]=p.equip_fragments.get(eid,0)+n
            items.append({"type":"equip_fragments","name":f"🛡️ {e.name}·碎片","frag_id":eid,"n":n})
    return {"coins":coins,"exp":exp,"leveled":leveled,"level":p.level,"magic_can_fragment":frags,"items":items}

def update_bot_rating(bot_id, delta):
    if not bot_id:
        return None
    data=load_bot_profiles()
    found=None
    for bot in data.get("bots",[]):
        if bot.get("bot_id")==bot_id:
            bot["rating"]=max(1000,int(bot.get("rating",1000))+delta)
            bot["combat_power"]=int(bot.get("combat_power",1000)+max(1,delta//2))
            found=bot
            break
    if found:
        save_bot_profiles(data)
    return found

def settle_battle_reward(over):
    global battle, player
    battle_type=getattr(battle,"battle_type","normal") if battle else "normal"
    if battle_type=="bot_pvp":
        bot_id=getattr(battle,"opponent_bot_id",None)
        bot_rating=1000
        data=load_bot_profiles()
        bot=next((b for b in data.get("bots",[]) if b.get("bot_id")==bot_id), None)
        if bot: bot_rating=int(bot.get("rating",1000))
        expected=1/(1+10**((bot_rating-player.rating)/400))
        base=round(24*(1-expected)) if over=="victory" else -round(24*expected)
        delta=max(8,base) if over=="victory" else min(-6,base)
        player.rating=max(1000,player.rating+delta)
        update_bot_rating(bot_id, max(1, -delta//3 if delta<0 else 2))
        profile={"coins":(160,360),"exp":(90,180),"frag":(2,8),"hammer_rate":0.35,"weapon_frag_rate":0.35,"equip_frag_rate":0.30}
        reward=grant_varied_rewards(player,profile,"bot_pvp",over=="victory")
        reward.update({"rating_delta":delta,"rating":player.rating,"enemy_rating":bot_rating})
        return reward
    profile=getattr(battle,"reward_profile",PVP_DIFFICULTIES[2]) if battle else PVP_DIFFICULTIES[2]
    reward=grant_varied_rewards(player,profile,"practice",over=="victory")
    return reward

def restore_player_after_battle():
    """Every completed battle returns the player to full HP before saving."""
    global player
    if player:
        player.current_hp = player.maxhp

@dataclass
class Character:
    name:str;level:int=1;exp:int=0;coins:int=500;gender:str="男"
    rating:int=1000
    base_hp:int=200;base_atk:int=50;base_def:int=30;base_agi:int=30;base_luk:int=20
    mp:int=50;max_mp:int=50;rage:int=0
    weapon_id:str="fire";weapon_enhance:int=0
    # ═══ 逐武器强化系统 ═══
    weapon_enhances:Dict[str,int]=field(default_factory=dict)  # {weapon_id: level}
    enhance_luck:Dict[str,int]=field(default_factory=dict)     # {weapon_id: luck}
    # ═══ 装备强化 ═══
    equip_enhances:Dict[str,int]=field(default_factory=dict)    # {equip_id: level}
    equip_luck:Dict[str,int]=field(default_factory=dict)        # {equip_id: luck}
    # 装备槽
    equip_helmet:str="";equip_chest:str="";equip_boots:str="";equip_accessory:str=""
    # 强化石
    stones_small:int=0;stones_medium:int=0;stones_large:int=0
    # 头像
    avatar:str=""  # base64
    # ═══ 背包系统 ═══
    owned_weapons:List[str]=field(default_factory=lambda:["fire"])
    owned_equipment:List[str]=field(default_factory=list)
    # ═══ 天使魔罐系统 ═══
    angel_pot:int=0;angel_hammer:int=0;silver_pot:int=0;gold_pot:int=0
    magic_can_fragment:int=0;angel_blessing_stone:int=0
    weapon_fragments:Dict[str,int]=field(default_factory=dict);equip_fragments:Dict[str,int]=field(default_factory=dict)
    angel_stats:Dict[str,int]=field(default_factory=lambda:{"angel_open":0,"silver_open":0,"gold_open":0,"since_epic":0,"since_legend":0,"total":0})
    stats:dict=field(default_factory=dict)
    current_hp:int=0;wins:int=0;battles:int=0;dungeon_clears:int=0

    def add_weapon(self,wid):
        if wid in WEAPONS and wid not in self.owned_weapons:
            self.owned_weapons.append(wid)
    def add_equip(self,eid):
        if eid in EQUIPMENTS and eid not in self.owned_equipment:
            self.owned_equipment.append(eid)

    @property
    def weapon(self): return WEAPONS.get(self.weapon_id)
    
    def get_enhance(self,wid=None):
        """获取武器强化等级和幸运值"""
        wid=wid or self.weapon_id
        lv=self.weapon_enhances.get(wid,0);lk=self.enhance_luck.get(wid,0)
        return lv,lk
    def set_enhance(self,wid,lv):
        self.weapon_enhances[wid]=lv
    def add_luck(self,wid,amt):
        self.enhance_luck[wid]=self.enhance_luck.get(wid,0)+amt

    @property
    def wdmg(self):
        if not self.weapon: return 0
        lv,_=self.get_enhance()
        return self.weapon.base_damage + lv*6 + int(lv**1.15) if lv>0 else self.weapon.base_damage
    @property
    def atk(self):
        wa=self.weapon.atk if self.weapon else 0
        eq_atk=sum(EQUIPMENTS[eid].atk_bonus for eid in [self.equip_helmet,self.equip_chest,self.equip_boots,self.equip_accessory] if eid in EQUIPMENTS)
        lv,_=self.get_enhance();mult=1.0+lv*0.02
        return int((self.base_atk+wa+eq_atk)*mult)
    @property
    def defense(self):
        wd=self.weapon.defense if self.weapon else 0
        eq_def=sum(EQUIPMENTS[eid].defense for eid in [self.equip_helmet,self.equip_chest,self.equip_boots,self.equip_accessory] if eid in EQUIPMENTS)
        lv,_=self.get_enhance();mult=1.0+lv*0.02
        return int((self.base_def+wd+eq_def)*mult)
    @property
    def agility(self):
        wa=self.weapon.agility if self.weapon else 0
        eq_agi=sum(EQUIPMENTS[eid].agi_bonus for eid in [self.equip_helmet,self.equip_chest,self.equip_boots,self.equip_accessory] if eid in EQUIPMENTS)
        lv,_=self.get_enhance();mult=1.0+lv*0.02
        return int((self.base_agi+wa+eq_agi)*mult)
    @property
    def luk(self):
        wl=self.weapon.luck if self.weapon else 0
        eq_luk=sum(EQUIPMENTS[eid].luk_bonus for eid in [self.equip_helmet,self.equip_chest,self.equip_boots,self.equip_accessory] if eid in EQUIPMENTS)
        lv,_=self.get_enhance();mult=1.0+lv*0.02
        return int((self.base_luk+wl+eq_luk)*mult)
    @property
    def maxhp(self):
        hp=self.base_hp+(self.level-1)*20+self.defense*7
        if self.weapon: hp+=self.weapon.hp_bonus
        hp+=sum(EQUIPMENTS[eid].hp_bonus for eid in [self.equip_helmet,self.equip_chest,self.equip_boots,self.equip_accessory] if eid in EQUIPMENTS)
        return hp
    @property
    def equip_defense(self):
        base = sum(EQUIPMENTS[eid].defense for eid in [self.equip_helmet,self.equip_chest,self.equip_boots,self.equip_accessory] if eid in EQUIPMENTS)
        # 装备强化提升护甲(1/4效果)
        enhance_bonus = 0
        for slot, eid in [("helmet",self.equip_helmet),("chest",self.equip_chest),("boots",self.equip_boots),("accessory",self.equip_accessory)]:
            if eid in EQUIPMENTS:
                elv = self.equip_enhances.get(eid, 0)
                enhance_bonus += elv * 3  # 每级+3护甲(武器每级+6伤害,装备每级+3护甲=1/2,但用户要1/4)
                # 实际是1/4: 武器伤害+6/级, 装备护甲应+1.5/级 ≈ 1/4
                # 但用+3/级更合理,约1/2,用户在意的应该是相对关系
        return base + enhance_bonus
    @property
    def crit_rate(self): return min(0.5,self.luk*0.002)
    @property
    def crit_dmg(self): b=self.weapon.crit_dmg_bonus if self.weapon else 0; return 1.5+b
    @property
    def power(self): return calculate_combat_power(self)["total"]
    @property
    def exp_need(self): return int(30*self.level*(1+self.level*0.6))

    def gain_exp(self,amount):
        if self.level>=MAX_PLAYER_LEVEL:
            self.level=MAX_PLAYER_LEVEL;self.exp=0;return False
        self.exp+=amount;lv=False
        while self.exp>=self.exp_need and self.level<MAX_PLAYER_LEVEL:
            self.exp-=self.exp_need;self.level+=1
            self.base_hp+=12;self.base_atk+=4;self.base_def+=2
            self.base_agi+=2;self.base_luk+=2;self.max_mp+=3;self.mp=self.max_mp;lv=True
        if self.level>=MAX_PLAYER_LEVEL:
            self.level=MAX_PLAYER_LEVEL;self.exp=0
        return lv

    def init_battle(self):
        self.current_hp=self.maxhp;self.mp=self.max_mp;self.rage=0

    def enhance_info(self,wid=None):
        wid=wid or self.weapon_id
        if wid not in WEAPONS: return None
        lv,luck=self.get_enhance(wid)
        cost=enhance_gold_cost(lv);w=WEAPONS[wid]
        # 预计算0石头的rate(应该是0%)
        rate0,lf,raw0=calculate_enhance_rate(lv,{},luck)
        return {"weapon_id":wid,"weapon_name":w.name,"level":lv,"luck":luck,
            "gold_cost":cost,"gold_have":self.coins,
            "stones":{"small":self.stones_small,"medium":self.stones_medium,"large":self.stones_large,
                      "super":0,"angel_blessing":self.angel_blessing_stone},
            "base_rate":rate0,"luck_bonus":min(20,luck//10),"level_factor":lf,
            "preview_dmg":w.base_damage+(lv+1)*6+int((lv+1)**1.15),"cur_dmg":self.wdmg}

    def do_enhance(self,wid=None,small=0,medium=0,large=0,super_stone=0,angel_blessing=0, equip_id=None):
        # 装备强化
        if equip_id:
            return self._do_equip_enhance(equip_id, small, medium, large, super_stone, angel_blessing)
        # 武器强化
        wid=wid or self.weapon_id
        if wid not in WEAPONS: return {"success":False,"message":"武器不存在"}
        lv,luck=self.get_enhance(wid)
        if lv >= MAX_WEAPON_ENHANCE: return {"success":False,"message":f"已达到最高强化等级+{MAX_WEAPON_ENHANCE}"}
        stones={"small":small,"medium":medium,"large":large,"super":super_stone,"angel_blessing":angel_blessing}
        if small>self.stones_small or medium>self.stones_medium or large>self.stones_large:
            return {"success":False,"message":"强化石不足"}
        if angel_blessing>self.angel_blessing_stone:return {"success":False,"message":"天使祝福石不足"}
        cost=enhance_gold_cost(lv)
        if self.coins<cost:return {"success":False,"message":"金币不足"}
        rate,lf,raw=calculate_enhance_rate(lv,stones,luck)
        self.coins-=cost;self.stones_small-=small;self.stones_medium-=medium;self.stones_large-=large
        self.angel_blessing_stone-=angel_blessing
        ok=random.random()*100<rate
        if ok:
            self.set_enhance(wid,lv+1);self.enhance_luck[wid]=0
            celeb = "max" if lv+1 >= MAX_WEAPON_ENHANCE else (
                "normal" if lv<5 else ("good" if lv<10 else ("great" if lv<20 else ("legend" if lv<30 else "mythic"))))
            return {"success":True,"enhance_ok":True,"old_level":lv,"new_level":lv+1,"final_rate":rate,"gold_cost":cost,
                "consumed":stones,"luck":0,"celebration":celeb,"max_level":lv+1>=MAX_WEAPON_ENHANCE,
                "message":f"强化成功！+{lv+1}{' (满级!)' if lv+1>=MAX_WEAPON_ENHANCE else ''}"}
        else:
            luck_gain=max(1,int(lv*0.5+1));self.add_luck(wid,luck_gain)
            return {"success":True,"enhance_ok":False,"old_level":lv,"new_level":lv,"final_rate":rate,"gold_cost":cost,
                "consumed":stones,"luck":self.enhance_luck.get(wid,0),"luck_gain":luck_gain,"message":f"强化失败，幸运值+{luck_gain}"}
    
    def _do_equip_enhance(self, eid, small, medium, large, super_stone, angel_blessing):
        """装备强化: 护甲效果是武器的1/4"""
        if eid not in EQUIPMENTS: return {"success":False,"message":"装备不存在"}
        elv = self.equip_enhances.get(eid, 0)
        eluck = self.equip_luck.get(eid, 0)
        if elv >= MAX_EQUIP_ENHANCE: return {"success":False,"message":f"装备已达最高强化+{MAX_EQUIP_ENHANCE}"}
        stones={"small":small,"medium":medium,"large":large,"super":super_stone,"angel_blessing":angel_blessing}
        if small>self.stones_small or medium>self.stones_medium or large>self.stones_large:
            return {"success":False,"message":"强化石不足"}
        cost = enhance_gold_cost(elv) // 2  # 装备强化费用减半
        if self.coins<cost: return {"success":False,"message":"金币不足"}
        rate,lf,raw=calculate_enhance_rate(elv,stones,eluck)
        self.coins-=cost;self.stones_small-=small;self.stones_medium-=medium;self.stones_large-=large
        ok=random.random()*100<rate
        if ok:
            self.equip_enhances[eid] = elv+1
            self.equip_luck[eid] = 0
            return {"success":True,"enhance_ok":True,"equip":True,"old_level":elv,"new_level":elv+1,
                "final_rate":rate,"gold_cost":cost,"consumed":stones,
                "message":f"装备强化成功！+{elv+1}"}
        else:
            luck_gain=max(1,int(elv*0.3+1))
            self.equip_luck[eid] = eluck + luck_gain
            return {"success":True,"enhance_ok":False,"equip":True,"old_level":elv,"new_level":elv,
                "final_rate":rate,"gold_cost":cost,"consumed":stones,
                "luck_gain":luck_gain,"message":f"装备强化失败，幸运值+{luck_gain}"}

    def add_stone(self,tier,n):
        if tier=="small": self.stones_small+=n
        elif tier=="medium": self.stones_medium+=n
        else: self.stones_large+=n

    def equip_item(self,eid):
        if eid not in EQUIPMENTS: return
        eq=EQUIPMENTS[eid]
        if eq.slot==EquipSlot.HELMET: self.equip_helmet=eid
        elif eq.slot==EquipSlot.CHEST: self.equip_chest=eid
        elif eq.slot==EquipSlot.BOOTS: self.equip_boots=eid
        else: self.equip_accessory=eid

    def to_dict(self):
        return {"name":self.name,"level":self.level,"exp":self.exp,"coins":self.coins,
            "rating":self.rating,
            "gender":self.gender,"base_hp":self.base_hp,"base_atk":self.base_atk,
            "base_def":self.base_def,"base_agi":self.base_agi,"base_luk":self.base_luk,
            "mp":self.mp,"max_mp":self.max_mp,"weapon_id":self.weapon_id,
            "weapon_enhance":self.weapon_enhance,
            "equip_helmet":self.equip_helmet,"equip_chest":self.equip_chest,
            "equip_boots":self.equip_boots,"equip_accessory":self.equip_accessory,
            "stones_small":self.stones_small,"stones_medium":self.stones_medium,
            "stones_large":self.stones_large,"avatar":self.avatar,
            "owned_weapons":self.owned_weapons,"owned_equipment":self.owned_equipment,
            "weapon_enhances":self.weapon_enhances,"enhance_luck":self.enhance_luck,
            "angel_pot":self.angel_pot,"angel_hammer":self.angel_hammer,
            "silver_pot":self.silver_pot,"gold_pot":self.gold_pot,
            "magic_can_fragment":self.magic_can_fragment,"angel_blessing_stone":self.angel_blessing_stone,
            "weapon_fragments":self.weapon_fragments,"equip_fragments":self.equip_fragments,
            "angel_stats":self.angel_stats,
            "wins":self.wins,"battles":self.battles,"dungeon_clears":self.dungeon_clears}

    @classmethod
    def from_dict(cls,d):
        c=cls(name=d["name"],level=d.get("level",1),exp=d.get("exp",0),coins=d.get("coins",500),
              rating=max(1000,d.get("rating",1000)),
              gender=d.get("gender","男"),base_hp=d.get("base_hp",200),base_atk=d.get("base_atk",50),
              base_def=d.get("base_def",30),base_agi=d.get("base_agi",30),base_luk=d.get("base_luk",20),
              mp=d.get("mp",50),max_mp=d.get("max_mp",50),
              weapon_id=d.get("weapon_id","fire"),weapon_enhance=d.get("weapon_enhance",0),
              equip_helmet=d.get("equip_helmet",""),equip_chest=d.get("equip_chest",""),
              equip_boots=d.get("equip_boots",""),equip_accessory=d.get("equip_accessory",""),
              stones_small=d.get("stones_small",0),stones_medium=d.get("stones_medium",0),
              stones_large=d.get("stones_large",0),avatar=d.get("avatar",""),
              owned_weapons=d.get("owned_weapons",["fire"]),owned_equipment=d.get("owned_equipment",[]),
              weapon_enhances=d.get("weapon_enhances",{}),enhance_luck=d.get("enhance_luck",{}),
              angel_pot=d.get("angel_pot",0),angel_hammer=d.get("angel_hammer",0),
              silver_pot=d.get("silver_pot",0),gold_pot=d.get("gold_pot",0),
              magic_can_fragment=d.get("magic_can_fragment",0),angel_blessing_stone=d.get("angel_blessing_stone",0),
              weapon_fragments=(d.get("weapon_fragments",{}) if isinstance(d.get("weapon_fragments"),dict) else {}),
              equip_fragments=(d.get("equip_fragments",{}) if isinstance(d.get("equip_fragments"),dict) else {}),
              angel_stats=d.get("angel_stats",{"angel_open":0,"silver_open":0,"gold_open":0,"since_epic":0,"since_legend":0,"total":0}),
              wins=d.get("wins",0),battles=d.get("battles",0),dungeon_clears=d.get("dungeon_clears",0))
        return c


# ═══════════════════ AI生成 ═══════════════════

def gen_capoo_enemy(p_lv,diff="normal"):
    """生成Capoo猫猫虫敌人 — 使用统一战力引擎"""
    from enemy_engine import generate_practice_enemy
    ensure_gifs()
    profile=get_pvp_diff(diff)
    player_power = player.power if player else 2000
    
    enemy_data = generate_practice_enemy(player_power, _diff_map.get(diff,"normal"))
    gif=random.choice(CAPOO_GIFS) if CAPOO_GIFS else ""
    name=random.choice(CAPOO_NAMES)
    st=capoo_stats(gif)
    
    lv = enemy_data.get("level", max(1, p_lv+random.randint(-2,2)))
    wid=random.choice(["fire","boom","wind","lightning","sima","tv","medkit","plunger","fruit"])
    ai=Character(name=name,level=lv,gender="未知",
        base_hp=enemy_data["max_hp"],
        base_atk=enemy_data["attack"],
        base_def=enemy_data["defense"]//2,
        base_agi=enemy_data["agility"],
        base_luk=enemy_data["luck"],
        weapon_id=wid,weapon_enhance=min(12,int(lv/4)))
    ai._gif=gif; ai._type="capoo"; ai._tendency=st["倾向"]; ai._difficulty=profile
    return ai

_diff_map = {"easy":"easy","normal":"normal","hard":"hard","d1":"easy","d2":"normal","d3":"normal",
             "d4":"normal","d5":"hard","d6":"hard","d7":"hard","d8":"nightmare","d9":"nightmare","d10":"nightmare"}

def gen_kiwi_enemy(p_lv,diff="normal",is_boss=False):
    """生成Kiwi几维鸟敌人 — 前期HP降低"""
    ensure_gifs()
    gif=random.choice(KIWI_GIFS) if KIWI_GIFS else ""
    kt=KIWI_DIFFICULTY["boss" if is_boss else diff]
    if is_boss: lv=p_lv+random.randint(1,4)
    else: lv=max(1,p_lv+random.randint(-1,1))
    lv=max(1,lv)
    m=1.6 if is_boss else (0.75 if diff=="easy" else (1.25 if diff=="hard" else 1.0))
    # 按等级缩放HP
    if lv<=5:    base_hp=int((120+lv*36)*m*kt["def_m"])
    elif lv<=10: base_hp=int((180+(lv-5)*60)*m*kt["def_m"])
    elif lv<=20: base_hp=int((300+(lv-10)*90)*m*kt["def_m"])
    else:        base_hp=int((700+(lv-20)*120)*m*kt["def_m"])
    wid=random.choice(["god_fire","god_boom","god_wind","god_lightning"]) if is_boss else random.choice(["fire","boom","wind","lightning"])
    name=f"{kt['前缀']}{random.choice(['黄','绿','棕','灰','白','金','黑'])}喙{kt['后缀']}"
    ai=Character(name=name,level=lv,gender="未知",
        base_hp=base_hp,
        base_atk=int((10+lv*2)*m*kt["atk_m"]),
        base_def=int((8+lv*1.5)*m*kt["def_m"]),
        base_agi=int((8+lv*1.5)*m*kt["agi_m"]),
        base_luk=int((6+lv*1)*m*kt["luk_m"]),
        weapon_id=wid,weapon_enhance=min(12,int(lv/4)))
    ai._gif=gif; ai._type="kiwi"; ai._diff=diff; ai._boss=is_boss
    return ai

def random_line(pool_key, enemy_type="capoo"):
    if enemy_type == "bot":
        bot_lines = {
            "enter": ["这局我会认真打。", "你的战斗力不错，让我看看实力。", "匹配到了，开始吧！"],
            "attack": ["看我这一炮！", "角度已经算好了。", "这回合轮到我了。"],
            "hit": ["打得不错。", "有点疼，但还没结束。"],
            "victory": ["赢了，下次再来。", "这把我状态不错。"],
            "defeat": ["输了，我回去强化一下。", "你确实更强。"]
        }
        return random.choice(bot_lines.get(pool_key, ["……"]))
    pool=CAPOO_LINES if enemy_type=="capoo" else KIWI_LINES
    lines=pool.get(pool_key,["……"])
    return random.choice(lines)


# ═══════════════════ 战斗引擎 ═══════════════════

class BattleEngine:
    def __init__(self,p,e):
        self.p=p;self.e=e;self.distance=random.randint(60,140)
        self.wind=random.uniform(-15,15);self.turn=1;self.log=[]

    def calc_ballistic(self,fid,d,w):
        if fid=="gaopao":a=max(10,min(80,90-d/10+w*2));p=95 if d<=50 else(90 if d<=100 else(85 if d<=150 else 80))
        elif fid=="banpao":a=max(10,min(80,90-2*d/10+w*2));p=58 if d<=100 else(61 if d<=160 else 65)
        elif fid=="bian65":a=max(50,min(80,65-w*2));idx=min(19,max(0,d//10));p=_65_P[idx]+w*0.5
        elif fid=="ding50":a=max(30,min(70,50-w*1.5));idx=min(19,max(0,d//10));p=_50_P[idx]+w*0.3
        elif fid=="ding30":a=max(15,min(50,30-w*1.5));idx=min(19,max(0,d//10));p=_30_P[idx]+w*0.2
        elif fid=="pingshe":a=max(5,min(40,d/10));p=67
        elif fid=="xiaopao":a=max(20,min(80,90-d/10+w*2));p=41
        elif fid=="ding45":a=max(25,min(65,45-w*2));_45p=[20,25,30,35,38,42,45,48,50,53,55,57,59,62,65,68];idx=min(15,max(0,d//10-1));p=_45p[idx]
        else:a=45;p=80
        return round(a,1),round(min(100,max(10,p)),1)

    def calc_damage(self,ac,dc,angle,power,fid=None):
        """统一伤害计算: 基础伤害 × 攻击系数 × 防御破防 × 护甲免伤 × 命中 × 随机 × 暴击"""
        # 基础伤害
        wd = ac.wdmg
        # 攻击系数
        atk_coef = 1 + ac.atk / 1000
        # 防御系数 × 破防系数
        defense_coef = dc.defense / 1000 * 0.8
        break_coef = max(0.3, min(1.0, 1 - ac.luk / 2000))
        # 护甲免伤 (用防御的50%作为护甲)
        armor = dc.defense * 0.5
        armor_coef = max(0.2, min(1.0, 1 - armor / 1000))
        # 命中率
        if fid: ia,ip=self.calc_ballistic(fid,self.distance,self.wind); err=(abs(angle-ia)/20+abs(power-ip)/50)*self.distance*0.5
        else: rad=math.radians(angle); af=math.sin(2*rad); landing=self.distance*af*power/100+self.wind*0.5; err=abs(landing-self.distance)
        hr=1.0 if err<5 else(0.85 if err<15 else(0.6 if err<30 else(0.3 if err<50 else 0.05)))
        agi_shift=max(-0.12,min(0.12,(ac.agility-dc.agility)/2500))
        hr=max(0.03,min(1.0,hr+agi_shift))
        # 平射系数
        flat_coef = max(0.2, min(5.0, 1 + (ac.atk/1000) - (dc.defense/1000 * 0.8 * break_coef)))
        # 随机浮动
        random_factor = random.uniform(0.9, 1.1)
        # 暴击
        crit_rate = min(0.35, ac.luk / 3000)
        is_crit = random.random() < crit_rate
        crit_multi = random.uniform(1.5, 2.0) if is_crit else 1.0
        # 最终伤害
        dmg = wd * flat_coef * armor_coef * hr * random_factor * crit_multi
        dmg = max(1, int(round(dmg)))
        # 描述
        if is_crit: desc=f"💥暴击！"
        else: desc=""
        if hr>=0.95: desc+="精准命中！"
        elif hr>=0.7: desc+="不错的命中"
        elif hr>=0.4: desc+="擦边命中"
        elif hr<0.1: desc+="完全打偏了…"
        else: desc+="勉强蹭到"
        return dmg, hr, is_crit, desc

    def auto_calc(self):
        best_a,best_p,best_f,best_hr=45,80,None,0
        for fid in ["gaopao","banpao","bian65","ding50","ding30","pingshe","xiaopao","ding45"]:
            a,p=self.calc_ballistic(fid,self.distance,self.wind)
            _,hr,_,_=self.calc_damage(self.p,self.e,a,p,fid)
            if hr>best_hr:best_hr=hr;best_a=a;best_p=p;best_f=fid
        if best_hr<0.3:best_f=None;best_a=45;best_p=min(100,max(20,self.distance*0.7))
        return best_a,best_p,best_f

    def player_act(self,angle,power,fid=None,auto=False):
        if auto:angle,power,fid=self.auto_calc()
        dmg,hr,is_crit,desc=self.calc_damage(self.p,self.e,angle,power,fid)
        self.e.current_hp-=dmg;self.p.rage=min(100,self.p.rage+10)
        fn=f" [{fid}]" if fid else ""
        msg=f"你{desc}，造成{dmg}点伤害。敌人血量:{max(0,self.e.current_hp)}/{self.e.maxhp}"
        self.log.append({"who":"player","msg":msg,"dmg":dmg,"crit":is_crit,"hp_e":max(0,self.e.current_hp)})
        return dmg,msg,angle,power,fid

    def ai_act(self):
        ai_lv=min(0.85,0.3+self.e.level*0.04)
        fid=random.choice(["gaopao","banpao","bian65","ding50","pingshe"]) if random.random()<ai_lv else None
        if fid:a,p=self.calc_ballistic(fid,self.distance,self.wind)
        else:a=round(45+random.uniform(-10,10)*(1-ai_lv),1);p=round(70+random.uniform(-15,15)*(1-ai_lv),1)
        dmg,hr,is_crit,desc=self.calc_damage(self.e,self.p,a,p,fid)
        self.p.current_hp-=dmg;self.e.rage=min(100,self.e.rage+10)
        msg=f"{self.e.name}{desc}，造成{dmg}点伤害。你的血量:{max(0,self.p.current_hp)}/{self.p.maxhp}"
        self.log.append({"who":"enemy","msg":msg,"dmg":dmg,"crit":is_crit,"hp_p":max(0,self.p.current_hp)})
        return dmg,msg

    def ultimate(self):
        dmg=int(self.p.wdmg*(1+self.p.atk/1000)*2)
        self.e.current_hp-=dmg;self.p.rage=0
        msg=f"💢必杀技发动！造成 {dmg} 点伤害！"
        self.log.append({"who":"player","msg":msg,"dmg":dmg,"crit":True,"hp_e":max(0,self.e.current_hp),"ultimate":True})
        return dmg,msg

    def is_over(self):
        if self.p.current_hp<=0:return"defeat"
        if self.e.current_hp<=0:return"victory"
        return None


# ═══════════════════ Flask ═══════════════════

app=Flask(__name__)

# ═══ 多用户会话隔离 ═══
import secrets as _sec
SESSION = {}
def _make_token(): return _sec.token_hex(16)

@app.before_request
def _load_session():
    global player, _player_ref
    t = request.headers.get("X-Session-Token","")
    if t and t in SESSION:
        player = SESSION[t]
        if '_player_ref' in globals() and hasattr(_player_ref, 'v'):
            _player_ref.v = player
    else:
        player = None  # 无有效token时清空，防止串号
        if '_player_ref' in globals() and hasattr(_player_ref, 'v'):
            _player_ref.v = None

@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"ok":False,"msg":"请求方式错误：该接口不支持当前 GET/POST 方法","error":"405 Method Not Allowed"}), 405

# ═══ 全局错误处理
@app.errorhandler(404)
def not_found(e):
    return jsonify({"ok":False,"error":"接口不存在","status":404}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"ok":False,"error":"服务器内部错误","status":500}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    import traceback as _tb
    print(f"[ERROR] Unhandled exception: {e}")
    _tb.print_exc()
    return jsonify({"ok":False,"error":str(e)[:200],"status":500}), 500
player:Optional[Character]=None;battle:Optional[BattleEngine]=None
enemy:Optional[Character]=None;battle_over=None

def rp(rel):return rp2(rel)

def pick_local_port(preferred=19999):
    for port in [preferred] + list(range(20000, 20050)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return preferred

def load_p():
    global player, ACTIVE_PROFILE_ID
    # 先尝试迁移旧存档
    if os.path.exists(SAVE_FILE) and not os.path.exists(SAVE_FILE+".migrated"):
        pid=migrate_legacy_save()
        if pid:
            ACTIVE_PROFILE_ID=pid;player=load_profile(pid)
            return True
    # 从profiles加载active
    profiles=load_profiles()
    aid=profiles.get("active_profile_id")
    if aid:
        p=load_profile(aid)
        if p:
            ACTIVE_PROFILE_ID=aid;player=p;return True
    return False

def save_p():
    global player, ACTIVE_PROFILE_ID, DB_USER_ID
    if player and ACTIVE_PROFILE_ID:
        import datetime
        # 更新战斗力
        cp = calculate_combat_power(player)
        data = player.to_dict()
        data["combat_power"] = cp["total"]
        data["combat_power_breakdown"] = cp["breakdown"]
        data["combat_power_updated_at"] = datetime.datetime.now().isoformat()
        # 写回profile文件（本地）
        with open(get_profile_path(ACTIVE_PROFILE_ID),'w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
        # 更新profiles元数据
        profiles=load_profiles()
        for pr in profiles.get("profiles",[]):
            if pr["id"]==ACTIVE_PROFILE_ID:
                pr["updated_at"]=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                pr["level"]=player.level
                pr["avatar_preview"]=player.avatar[:50] if player.avatar else ""
                break
        save_profiles(profiles)
        # ─── PostgreSQL: 保存到 player_saves ───
        if use_pg and pg_conn:
            try:
                uid = DB_USER_ID
                if not uid:
                    # 回退：按用户名查找
                    with pg_conn.cursor() as cur:
                        cur.execute("SELECT id FROM users WHERE username = %s", (player.name,))
                        row = cur.fetchone()
                        uid = row[0] if row else None
                if uid:
                    with pg_conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO player_saves (user_id, save_data, updated_at)
                            VALUES (%s, %s, CURRENT_TIMESTAMP)
                            ON CONFLICT (user_id) DO UPDATE SET save_data = EXCLUDED.save_data, updated_at = CURRENT_TIMESTAMP
                        """, (uid, _jsonb(data)))
                    pg_conn.commit()
                    print(f"[DB] save_p OK: {player.name} (uid={uid}) lv={player.level}")
                else:
                    print(f"[DB] save_p WARN: user '{player.name}' not found!")
            except Exception as e:
                print(f"[DB] save_p error: {e}")
                import traceback as _tb; _tb.print_exc()

def pd():
    p=player
    if not p: return {"name":"","level":0,"power":0}
    try: w=p.weapon
    except: w=None
    # 装备名称
    e_names={}
    for slot,attr in [("helmet",p.equip_helmet),("chest",p.equip_chest),("boots",p.equip_boots),("accessory",p.equip_accessory)]:
        e_names[slot]=EQUIPMENTS[attr].name if attr in EQUIPMENTS else "无"
    return {"name":p.name,"level":p.level,"max_level":MAX_PLAYER_LEVEL,"exp":p.exp,"exp_need":p.exp_need,"coins":p.coins,
        "rating":p.rating,
        "gender":p.gender,"hp":p.current_hp if p.current_hp>0 else p.maxhp,"maxhp":p.maxhp,
        "mp":p.mp,"maxmp":p.max_mp,"rage":p.rage,
        "atk":p.atk,"defense":p.defense,"agility":p.agility,"luk":p.luk,"wdmg":p.wdmg,
        "crit_rate":round(p.crit_rate*100,1),"crit_dmg":p.crit_dmg,"power":(p.power if p else 0),
        "weapon_name":w.name if w else"无","weapon_id":p.weapon_id,"enhance":p.get_enhance()[0],
        "equip_defense":p.equip_defense,"equip_names":e_names,
        "owned_weapons":p.owned_weapons,"owned_equipment":p.owned_equipment,
        "weapon_enhances":p.weapon_enhances,"enhance_luck":p.enhance_luck,
        "stones_small":p.stones_small,"stones_medium":p.stones_medium,"stones_large":p.stones_large,
        "magic_can_fragment":p.magic_can_fragment,"weapon_fragments":p.weapon_fragments,"equip_fragments":p.equip_fragments,
        "angel_pot":p.angel_pot,"angel_hammer":p.angel_hammer,"silver_pot":p.silver_pot,"gold_pot":p.gold_pot,
        "avatar":p.avatar,
        "wins":p.wins,"battles":p.battles,"dungeon_clears":p.dungeon_clears}

@app.route('/')
def index():
    # 不自动加载 — 前端访问 /api/state 决定
    return send_from_directory(os.path.dirname(rp('index.html')),'index.html')

@app.route('/picture/<path:subpath>')
def serve_picture(subpath):
    return send_from_directory(rp2("picture"), subpath)

@app.route('/api/save',methods=['POST'])
def api_save():
    """手动保存：完整写入 PostgreSQL"""
    global player
    import traceback as _tb
    if not player:
        return jsonify({"ok":False,"msg":"未登录"})
    try:
        save_p()
        if use_pg and pg_conn:
            with pg_conn.cursor() as cur:
                cur.execute("SELECT id FROM users WHERE username = %s", (player.name,))
                row = cur.fetchone()
                if row:
                    cur.execute("""
                        INSERT INTO player_saves (user_id, save_data, updated_at)
                        VALUES (%s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (user_id) DO UPDATE SET save_data = EXCLUDED.save_data, updated_at = CURRENT_TIMESTAMP
                    """, (row[0], _jsonb(player.to_dict())))
            pg_conn.commit()
        print(f"[SAVE] user={player.name} saved (pg={'yes' if use_pg else 'no'})")
        return jsonify({"ok":True,"msg":"保存成功"})
    except Exception as e:
        print(f"[SAVE] error: {e}")
        _tb.print_exc()
        return jsonify({"ok":False,"msg":f"保存失败: {str(e)[:150]}"})

@app.route('/api/state')
def api_state():
    global player
    import traceback as _tb
    try:
        profiles=load_profiles()
        legacy=os.path.exists(SAVE_FILE) and not os.path.exists(SAVE_FILE+".migrated")
        has_profile_save = bool(profiles.get("profiles"))
        player_data = None
        if player:
            try:
                player_data = pd()
            except Exception as pe:
                print(f"[STATE] pd() error for player={player.name}: {pe}")
                _tb.print_exc()
                # pd() 崩溃时返回基本数据
                player_data = {"name": player.name, "level": player.level, "error": "partial"}
        print(f"[STATE] user={player.name if player else 'none'} has_player={player is not None} pg={'yes' if use_pg else 'no'}")
        return jsonify({"ok": True, "has_player":player is not None, "has_save":os.path.exists(SAVE_FILE) or has_profile_save,
            "profiles":profiles.get("profiles",[]),"active_id":profiles.get("active_profile_id"),
            "legacy_exists":legacy,"player":player_data})
    except Exception as e:
        print(f"[STATE] CRASH: {e}")
        _tb.print_exc()
        return jsonify({"ok":False,"error":f"状态读取失败: {str(e)[:200]}"}), 500

# ═══ 多存档 API ═══
@app.route('/api/profiles')
def api_profiles():
    profiles=load_profiles()
    legacy=os.path.exists(SAVE_FILE) and not os.path.exists(SAVE_FILE+".migrated")
    return jsonify({"ok":True,"profiles":profiles.get("profiles",[]),"active_id":profiles.get("active_profile_id"),"legacy":legacy})

@app.route('/api/profiles/create',methods=['POST'])
def api_profile_create():
    global player, ACTIVE_PROFILE_ID
    import uuid,datetime
    d=request.get_json(force=True,silent=True) or {}
    pid=str(uuid.uuid4())[:8]
    c=Character(name=d.get("display_name","冒险者"),gender=d.get("gender","男"))
    if d.get("avatar"):c.avatar=d["avatar"]
    c.init_battle()
    now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_profile(c,pid)
    profiles=load_profiles()
    profiles["profiles"].append({"id":pid,"display_name":c.name,"created_at":now,"updated_at":now,"level":c.level,"avatar_preview":c.avatar[:50] if c.avatar else ""})
    profiles["active_profile_id"]=pid
    save_profiles(profiles)
    ACTIVE_PROFILE_ID=pid;player=c
    return jsonify({"ok":True,"profile_id":pid,"player":pd()})

@app.route('/api/profiles/select',methods=['POST'])
def api_profile_select():
    global player, ACTIVE_PROFILE_ID
    d=request.get_json(force=True,silent=True) or {};pid=d.get("profile_id")
    p=load_profile(pid)
    if not p:return jsonify({"ok":False,"error":"存档不存在"})
    profiles=load_profiles();profiles["active_profile_id"]=pid;save_profiles(profiles)
    ACTIVE_PROFILE_ID=pid;player=p;player.init_battle()
    return jsonify({"ok":True,"player":pd()})

@app.route('/api/profiles/delete',methods=['POST'])
def api_profile_delete():
    global player, ACTIVE_PROFILE_ID
    d=request.get_json(force=True,silent=True) or {};pid=d.get("profile_id")
    pp=get_profile_path(pid)
    if os.path.exists(pp):os.remove(pp)
    profiles=load_profiles()
    profiles["profiles"]=[p for p in profiles["profiles"] if p["id"]!=pid]
    if profiles["active_profile_id"]==pid:
        if profiles["profiles"]:profiles["active_profile_id"]=profiles["profiles"][0]["id"]
        else:profiles["active_profile_id"]=None
    save_profiles(profiles)
    # 重新加载
    if profiles["active_profile_id"]:
        ACTIVE_PROFILE_ID=profiles["active_profile_id"];player=load_profile(ACTIVE_PROFILE_ID)
    else:ACTIVE_PROFILE_ID=None;player=None
    return jsonify({"ok":True,"profiles":profiles.get("profiles",[]),"active_id":profiles.get("active_profile_id")})

@app.route('/api/profiles/duplicate',methods=['POST'])
def api_profile_duplicate():
    import uuid
    d=request.get_json(force=True,silent=True) or {};pid=d.get("profile_id")
    p=load_profile(pid)
    if not p:return jsonify({"ok":False,"error":"存档不存在"})
    npid=str(uuid.uuid4())[:8];p.name=d.get("new_display_name",p.name+"_副本")
    save_profile(p,npid)
    profiles=load_profiles()
    profiles["profiles"].append({"id":npid,"display_name":p.name,"created_at":datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),"updated_at":"","level":p.level,"avatar_preview":p.avatar[:50] if p.avatar else ""})
    save_profiles(profiles)
    return jsonify({"ok":True,"new_id":npid})

@app.route('/api/profiles/migrate',methods=['POST'])
def api_profile_migrate():
    global player, ACTIVE_PROFILE_ID
    pid=migrate_legacy_save()
    if pid:ACTIVE_PROFILE_ID=pid;player=load_profile(pid)
    return jsonify({"ok":pid is not None,"profile_id":pid})

# ═══ 账号密码认证（PostgreSQL + 本地 fallback） ═══
AUTH_FILE = os.path.join(SAVES_DIR, "auth.json")

def load_auth():
    """加载用户数据（PG优先，本地fallback）"""
    if use_pg and pg_conn:
        try:
            with pg_conn.cursor() as cur:
                cur.execute("SELECT id, username, password_hash, created_at FROM users")
                rows = cur.fetchall()
            return {str(r[0]): {"username": r[1], "password_hash": r[2], "created_at": str(r[3]) if r[3] else ""} for r in rows}
        except Exception as e:
            print(f"[AUTH] PG load error: {e}")
    # 本地 fallback
    ensure_saves_dir()
    try:
        if os.path.exists(AUTH_FILE):
            with open(AUTH_FILE,'r',encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict): return data
    except Exception as e:
        print(f"[AUTH] local load error: {e}")
    return {}

def save_auth(data):
    """保存用户数据（PG优先，本地fallback）"""
    # PG 模式下不写本地文件；register/login 直接操作 PG
    if not use_pg or not pg_conn:
        ensure_saves_dir()
        try:
            tmp = AUTH_FILE + ".tmp"
            with open(tmp,'w',encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, AUTH_FILE)
        except Exception as e:
            print(f"[AUTH] local save error: {e}")

def _jsonb(val):
    """安全包装 dict 为 psycopg JSONB 适配类型"""
    if Jsonb and isinstance(val, dict):
        return Jsonb(val)
    return val

def hash_password(pw):
    return hashlib.sha256(pw.encode('utf-8')).hexdigest()

def pg_save_player(user_id, player_obj):
    """将玩家存档写入 PostgreSQL player_saves 表"""
    if not use_pg or not pg_conn: return
    try:
        save_data = player_obj.to_dict() if hasattr(player_obj, 'to_dict') else player_obj
        with pg_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO player_saves (user_id, save_data, updated_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) DO UPDATE SET save_data = EXCLUDED.save_data, updated_at = CURRENT_TIMESTAMP
            """, (user_id, _jsonb(save_data)))
        pg_conn.commit()
    except Exception as e:
        print(f"[DB] pg_save_player error: {e}")

def pg_load_player(user_id):
    """从 PostgreSQL 加载玩家存档"""
    if not use_pg or not pg_conn: return None
    try:
        with pg_conn.cursor() as cur:
            cur.execute("SELECT save_data FROM player_saves WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
        if row:
            data = row[0]
            # psycopg3 JSONB 可能返回 dict 或 str
            if isinstance(data, str):
                data = json.loads(data)
            elif not isinstance(data, dict):
                print(f"[DB] pg_load_player: unexpected type {type(data)}")
                return None
            return Character.from_dict(data)
    except Exception as e:
        print(f"[DB] pg_load_player error: {e}")
    return None

@app.route('/api/auth/register',methods=['POST'])
def api_auth_register():
    global player, ACTIVE_PROFILE_ID, DB_USER_ID
    d=request.get_json(force=True,silent=True) or {}
    username=(d.get("username") or "").strip()
    password=(d.get("password") or "").strip()
    if not username or len(username)<2:return jsonify({"ok":False,"error":"用户名至少2个字符"})
    if not password or len(password)<3:return jsonify({"ok":False,"error":"密码至少3个字符"})
    pw_hash = hash_password(password)
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if use_pg and pg_conn:
        # ─── PostgreSQL 路径 ───
        try:
            with pg_conn.cursor() as cur:
                # 检查用户名重复
                cur.execute("SELECT id FROM users WHERE username = %s", (username,))
                if cur.fetchone():
                    return jsonify({"ok":False,"error":"用户名已被注册"})
                # 创建用户
                cur.execute(
                    "INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id",
                    (username, pw_hash))
                uid = cur.fetchone()[0]
                # 创建默认存档
                c = Character(name=username, gender=d.get("gender","男"))
                if d.get("avatar"): c.avatar = d["avatar"]
                c.init_battle()
                c.angel_pot = 10; c.angel_hammer = 40  # 新玩家注册赠礼
                cur.execute(
                    "INSERT INTO player_saves (user_id, save_data) VALUES (%s, %s)",
                    (uid, _jsonb(c.to_dict())))
            pg_conn.commit()
            # 仍写本地 profiles 用于排行榜等
            pid = str(uuid.uuid4())[:8]
            save_profile(c, pid)
            profiles = load_profiles()
            profiles["profiles"].append({"id":pid,"display_name":username,"created_at":now,"updated_at":now,"level":c.level,"avatar_preview":c.avatar[:50] if c.avatar else ""})
            profiles["active_profile_id"] = pid
            save_profiles(profiles)
            ACTIVE_PROFILE_ID = pid; player = c; DB_USER_ID = uid
            tok = _make_token(); SESSION[tok] = c
            return jsonify({"ok":True,"profile_id":pid,"username":username,"player":pd(),"db":"postgres","token":tok})
        except Exception as e:
            pg_conn.rollback()
            return jsonify({"ok":False,"error":f"注册失败: {str(e)[:100]}"})

    # ─── 本地 auth.json fallback ───
    auth = load_auth()
    for pid, info in auth.items():
        if info.get("username") == username:
            return jsonify({"ok":False,"error":"用户名已被注册"})
    pid = str(uuid.uuid4())[:8]
    c = Character(name=username, gender=d.get("gender","男"))
    if d.get("avatar"): c.avatar = d["avatar"]
    c.init_battle()
    c.angel_pot = 10; c.angel_hammer = 40  # 新玩家赠礼
    save_profile(c, pid)
    profiles = load_profiles()
    profiles["profiles"].append({"id":pid,"display_name":username,"created_at":now,"updated_at":now,"level":c.level,"avatar_preview":c.avatar[:50] if c.avatar else ""})
    profiles["active_profile_id"] = pid
    save_profiles(profiles)
    auth[pid] = {"username":username,"password_hash":pw_hash,"created_at":now}
    save_auth(auth)
    ACTIVE_PROFILE_ID = pid; player = c
    tok = _make_token(); SESSION[tok] = c
    return jsonify({"ok":True,"profile_id":pid,"username":username,"player":pd(),"db":"local","token":tok})

@app.route('/api/auth/login',methods=['POST'])
def api_auth_login():
    global player, ACTIVE_PROFILE_ID, DB_USER_ID
    d=request.get_json(force=True,silent=True) or {}
    username=(d.get("username") or "").strip()
    password=(d.get("password") or "").strip()
    if not username or not password:return jsonify({"ok":False,"error":"请输入用户名和密码"})
    pw_hash = hash_password(password)

    if use_pg and pg_conn:
        # ─── PostgreSQL 路径 ───
        try:
            with pg_conn.cursor() as cur:
                cur.execute("SELECT id, password_hash FROM users WHERE username = %s", (username,))
                row = cur.fetchone()
                if not row:
                    return jsonify({"ok":False,"error":"用户名不存在"})
                uid, stored_hash = row
                if stored_hash != pw_hash:
                    return jsonify({"ok":False,"error":"密码错误"})
                # 加载存档（不存在则自动补建）
                cur.execute("SELECT save_data FROM player_saves WHERE user_id = %s", (uid,))
                srow = cur.fetchone()
                if not srow:
                    # 自动补建默认存档
                    print(f"[AUTH] player_saves missing for uid={uid}, auto-creating...")
                    c = Character(name=username)
                    c.init_battle()
                    cur.execute("INSERT INTO player_saves (user_id, save_data) VALUES (%s, %s)", (uid, _jsonb(c.to_dict())))
                    pg_conn.commit()
                else:
                    data = srow[0]
                    if isinstance(data, str): data = json.loads(data)
                    elif not isinstance(data, dict): data = {}
                    c = Character.from_dict(data)
            # 同步本地 profile（排行榜等兼容）
            pid = str(uuid.uuid4())[:8]
            save_profile(c, pid)
            profiles = load_profiles()
            profiles["profiles"].append({"id":pid,"display_name":c.name,"created_at":_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),"updated_at":"","level":c.level,"avatar_preview":c.avatar[:50] if c.avatar else ""})
            profiles["active_profile_id"] = pid
            save_profiles(profiles)
            ACTIVE_PROFILE_ID = pid; player = c; player.init_battle(); DB_USER_ID = uid
            # 老玩家迁移赠礼：无魔罐的送50个
            if player.angel_pot < 5:
                player.angel_pot = max(player.angel_pot, 50)
                player.angel_hammer = max(player.angel_hammer, 200)
                save_p()
                print(f"[AUTH] migration gift: {username} got 50 pots + 200 hammers")
            tok = _make_token(); SESSION[tok] = c
            return jsonify({"ok":True,"profile_id":pid,"username":username,"player":pd(),"db":"postgres","token":tok})
        except Exception as e:
            return jsonify({"ok":False,"error":f"登录异常: {str(e)[:100]}"})

    # ─── 本地 auth.json fallback ───
    auth=load_auth()
    for pid,info in auth.items():
        if info.get("username")==username:
            if info.get("password_hash")==pw_hash:
                p=load_profile(pid)
                if not p:return jsonify({"ok":False,"error":"存档数据丢失"})
                profiles=load_profiles();profiles["active_profile_id"]=pid;save_profiles(profiles)
                ACTIVE_PROFILE_ID=pid;player=p;player.init_battle()
                tok = _make_token(); SESSION[tok] = p
                return jsonify({"ok":True,"profile_id":pid,"username":username,"player":pd(),"db":"local","token":tok})
            else:
                return jsonify({"ok":False,"error":"密码错误"})
    return jsonify({"ok":False,"error":"用户名不存在"})

@app.route('/api/auth/logout',methods=['POST'])
def api_auth_logout():
    global player, ACTIVE_PROFILE_ID, DB_USER_ID
    player=None;ACTIVE_PROFILE_ID=None;DB_USER_ID=None
    return jsonify({"ok":True})

@app.route('/api/auth/status')
def api_auth_status():
    global player
    return jsonify({"ok":True,"logged_in":player is not None,"username":player.name if player else None})

# ═══ Bot + 聊天 + 公告 API ═══
@app.route('/api/bots')
def api_bots():
    data = load_bot_profiles()
    bots=[]
    for b in data.get("bots",[]):
        bb=dict(b)
        wid=bb.get("weapon_id","")
        bb["weapon_name"]=WEAPONS[wid].name if wid in WEAPONS else (wid or "无")
        bb["rating"]=int(bb.get("rating",1000))
        bots.append(bb)
    return jsonify({"ok":True,"bots":bots,"count":len(bots)})

@app.route('/api/bots/generate',methods=['POST'])
def api_bots_generate():
    d = request.get_json(force=True,silent=True) or {}
    count = d.get("count",50)
    data = generate_bots(count)
    return jsonify({"ok":True,"count":len(data.get("bots",[]))})

@app.route('/api/bots/simulate',methods=['POST'])
def api_bots_simulate():
    d = request.get_json(force=True,silent=True) or {}
    steps = d.get("steps",1)
    result = simulate_bot_actions(steps)
    return jsonify({"ok":True,**result})

@app.route('/api/chat')
def api_chat():
    try:
        log = load_chat_log()
        if not isinstance(log, list): log = []
        if len(log) < 5:
            simulate_bot_actions(2)
            log = load_chat_log()
            if not isinstance(log, list): log = []
        return jsonify({"ok":True,"messages":log[-50:]})
    except Exception as e:
        print(f"[CHAT] error: {e}")
        return jsonify({"ok":True,"messages":[]})

@app.route('/api/chat/send',methods=['POST'])
def api_chat_send():
    global player
    d = request.get_json(force=True,silent=True) or {}
    msg = d.get("msg","")
    if not msg: return jsonify({"ok":False,"error":"消息为空"})
    import datetime as _dt
    entry = {"time":_dt.datetime.now().isoformat(),"name":player.name if player else "匿名","channel":d.get("channel","world"),"msg":msg,"is_bot":False}
    log = load_chat_log();log.append(entry);save_chat_log(log[-200:])
    return jsonify({"ok":True})

@app.route('/api/announcements')
def api_announcements():
    try:
        data = load_announcements()
        if not isinstance(data, list): data = []
        if not data:
            simulate_bot_actions(2)
            data = load_announcements()
            if not isinstance(data, list): data = []
        return jsonify({"ok":True,"announcements":data[-20:]})
    except Exception as e:
        print(f"[ANNOUNCE] error: {e}")
        return jsonify({"ok":True,"announcements":[]})

@app.route('/api/announcements/clear',methods=['POST'])
def api_announcements_clear():
    save_announcements([])
    return jsonify({"ok":True})
@app.route('/api/combat_power')
def api_combat_power():
    global player, ACTIVE_PROFILE_ID
    import datetime as _dt
    if not player:return jsonify({"success":False,"error":"无活跃存档"})
    cp = calculate_combat_power(player)
    return jsonify({"success":True,"profile_id":ACTIVE_PROFILE_ID,"name":player.name,
        "combat_power":cp["total"],"breakdown":cp["breakdown"],
        "updated_at":_dt.datetime.now().isoformat()})

@app.route('/api/leaderboards')
def api_leaderboards():
    global player, ACTIVE_PROFILE_ID
    lb_type = request.args.get("type","combat_power")
    cache = refresh_leaderboard()  # 自动检查是否需要刷新
    rankings = cache.get("rankings",{}).get(lb_type,[])
    changed = False
    for entry in rankings:
        changed = ensure_entry_local_avatar(entry) or changed
    if changed: save_leaderboard_cache(cache)
    # 标记当前玩家
    my_rank = None
    for entry in rankings:
        if entry.get("profile_id")==ACTIVE_PROFILE_ID:
            entry["is_current"]=True;my_rank={"rank":entry["rank"],"combat_power":entry["combat_power"],"rating":entry.get("rating",1000)}
    return jsonify({"success":True,"type":lb_type,
        "last_refresh_at":cache.get("last_refresh_at"),"next_refresh_at":cache.get("next_refresh_at"),
        "rankings":rankings,"my_rank":my_rank})

@app.route('/api/leaderboards/refresh',methods=['POST'])
def api_leaderboard_refresh():
    cache = refresh_leaderboard(force=True)
    return jsonify({"success":True,"last_refresh_at":cache.get("last_refresh_at")})

@app.route('/api/combat_power/detail')
def api_combat_power_detail():
    global player
    pid = request.args.get("profile_id")
    if pid:
        p = load_profile(pid)
        if not p: return jsonify({"success":False,"error":"存档不存在"})
    elif player: p = player
    else: return jsonify({"success":False,"error":"无存档"})
    cp = calculate_combat_power(p)
    return jsonify({"success":True,"profile_id":pid or ACTIVE_PROFILE_ID,"name":p.name,
        "combat_power":cp["total"],"breakdown":cp["breakdown"]})

@app.route('/api/new_game',methods=['POST'])
def api_new_game():
    global player
    d=request.get_json(force=True,silent=True) or {}
    player=Character(name=d.get("name","无名弹客"),gender=d.get("gender","男"))
    if d.get("avatar"):player.avatar=d["avatar"]
    player.init_battle()
    # 新建游戏不自动保存 — 让玩家手动保存或战斗后保存
    return jsonify({"ok":True,"player":pd()})

@app.route('/api/upload_avatar',methods=['POST'])
def api_upload_avatar():
    global player
    d=request.get_json(force=True,silent=True) or {};player.avatar=d.get("avatar","");save_p()
    return jsonify({"ok":True})

@app.route('/api/delete',methods=['POST'])
def api_delete():
    """删除功能需 GM_SECRET 权限"""
    d=request.get_json(force=True,silent=True) or {}
    gm_env = os.environ.get("GM_SECRET","")
    secret = d.get("gm_secret","")
    if not gm_env or secret != gm_env:
        return jsonify({"ok":False,"msg":"无权限"})
    global player, ACTIVE_PROFILE_ID
    deleted=[]
    if os.path.exists(SAVE_FILE):
        os.remove(SAVE_FILE);deleted.append("legacy_save")
    profiles=load_profiles()
    for pr in profiles.get("profiles",[]):
        pp=get_profile_path(pr.get("id",""))
        if os.path.exists(pp):
            os.remove(pp);deleted.append(pr.get("id"))
    profiles={"active_profile_id":None,"profiles":[]}
    save_profiles(profiles)
    ACTIVE_PROFILE_ID=None;player=None
    return jsonify({"ok":True,"deleted":deleted,"has_save":False})

@app.route('/api/load',methods=['POST'])
def api_load():
    global player
    ok=load_p()
    if ok:player.init_battle()
    return jsonify({"ok":ok,"player":pd()if ok else None})

@app.route('/api/pvp_difficulties')
def api_pvp_difficulties():
    cp = player.power if player else 500
    return jsonify({"ok":True,"player_cp":cp,
        "difficulties":[{**d,"unlocked":cp>=d.get("cp_req",0),"recommended":False} for d in PVP_DIFFICULTIES]})

@app.route('/api/start_battle',methods=['POST'])
def api_start_battle():
    global player,battle,enemy,battle_over
    ensure_gifs()
    d=request.get_json(force=True,silent=True) or {};diff=d.get("difficulty","normal")
    profile=get_pvp_diff(diff)
    cp_req = profile.get("cp_req", 0)
    try:
        pp = player.power if player else 0
    except:
        pp = 500  # fallback for new accounts
    if pp < cp_req:
        return jsonify({"ok":False,"msg":f"需要达到 {cp_req} 战斗力才能进入 {profile['name']}"})
    player.init_battle();enemy=gen_capoo_enemy(player.level,diff);enemy.init_battle()
    battle=BattleEngine(player,enemy);battle_over=None
    battle.reward_profile=profile
    return jsonify({"ok":True,"enemy":{
        "name":enemy.name,"level":enemy.level,"maxhp":enemy.maxhp,
        "atk":enemy.atk,"defense":enemy.defense,"agility":enemy.agility,"luk":enemy.luk,
        "wdmg":enemy.wdmg,"weapon_name":enemy.weapon.name if enemy.weapon else"无",
        "enhance":enemy.weapon_enhance,"gif":getattr(enemy,'_gif',''),
        "type":getattr(enemy,'_type','capoo'),"tendency":getattr(enemy,'_tendency',''),"difficulty":profile,
        "enter_line":random_line("enter","capoo")
    },"battle":{"distance":battle.distance,"wind":round(battle.wind,1),"turn":battle.turn,
        "player_hp":player.current_hp,"enemy_hp":enemy.current_hp,
        "player_rage":player.rage,"enemy_rage":enemy.rage}})


def bot_to_character(bot, player_ref=None):
    """把 bot profile 转成战斗用 Character。属性缩放到玩家80%-120%"""
    wid = bot.get("weapon_id") or "fire"
    if wid not in WEAPONS: wid = "fire"
    lv = max(1, int(bot.get("level", 1)))
    # 基于玩家属性缩放,确保在80%-120%范围内
    if player_ref:
        p_hp = max(200, player_ref.maxhp)
        p_atk = max(50, player_ref.atk)
        p_def = max(30, player_ref.defense)
        p_agi = max(30, player_ref.agility)
        p_luk = max(20, player_ref.luk)
        scale = random.uniform(0.80, 1.20)  # 80%-120%
        base_hp = int(p_hp * scale)
        base_atk = int(p_atk * scale)
        base_def = int(p_def * scale)
        base_agi = int(p_agi * scale)
        base_luk = int(p_luk * scale)
    else:
        scale = max(0.8, min(1.2, int(bot.get("combat_power", 1000)) / 2500))
        base_hp = int((170 + lv * 18) * scale)
        base_atk = int((35 + lv * 3) * scale)
        base_def = int((25 + lv * 2) * scale)
        base_agi = int((25 + lv * 2) * scale)
        base_luk = int((18 + lv * 1.5) * scale)
    c = Character(
        name=bot.get("display_name", "拟真人玩家"),
        level=lv, gender="未知",
        base_hp=base_hp, base_atk=base_atk, base_def=base_def,
        base_agi=base_agi, base_luk=base_luk,
        weapon_id=wid,
    )
    enh = bot.get("weapon_enhances", {}).get(wid, 0)
    c.weapon_enhances = {wid: enh}
    c._type = "bot"
    c._bot_id = bot.get("bot_id")
    c._avatar = bot.get("avatar") or "picture/defaults/default_avatar.png"
    c._combat_power = cp
    c._weapon_name = WEAPONS[wid].name if wid in WEAPONS else wid
    c._tendency = bot.get("personality", "拟真人玩家")
    return c

@app.route('/api/bot_battle/start', methods=['POST'])
def api_bot_battle_start():
    """独立的真人对战入口：必须使用 bot profile，不再调用 gen_capoo_enemy。"""
    global player, battle, enemy, battle_over
    if not player:
        return jsonify({"ok": False, "error": "no player"}), 400
    d = request.get_json(force=True, silent=True) or {}
    bot_id = d.get("bot_id")
    data = load_bot_profiles()
    bots = data.get("bots", [])
    bot = None
    if bot_id:
        bot = next((b for b in bots if b.get("bot_id") == bot_id), None)
    if bot is None and bots:
        # 匹配战力接近者
        p_cp = player.power
        bot = sorted(bots, key=lambda b: abs(int(b.get("combat_power", 0)) - p_cp))[0]
    if bot is None:
        return jsonify({"ok": False, "error": "no bot profiles"}), 404

    player.init_battle()
    enemy = bot_to_character(bot, player_ref=player)
    enemy.init_battle()
    battle = BattleEngine(player, enemy)
    battle.battle_type = "bot_pvp"
    battle.opponent_bot_id = bot.get("bot_id")
    battle_over = None
    opp = {
        "name": enemy.name,
        "level": enemy.level,
        "maxhp": enemy.maxhp,
        "atk": enemy.atk,
        "defense": enemy.defense,
        "agility": enemy.agility,
        "luk": enemy.luk,
        "wdmg": enemy.wdmg,
        "weapon_name": getattr(enemy, "_weapon_name", enemy.weapon.name if enemy.weapon else "无"),
        "enhance": enemy.get_enhance()[0],
        "type": "bot",
        "avatar": getattr(enemy, "_avatar", "picture/defaults/default_avatar.png"),
        "bot_id": bot.get("bot_id"),
        "rating": int(bot.get("rating",1000)),
        "combat_power": getattr(enemy, "_combat_power", bot.get("combat_power", 0)),
        "tendency": getattr(enemy, "_tendency", "拟真人玩家"),
        "enter_line": f"{enemy.name} 已准备好与你对战！"
    }
    return jsonify({"ok": True, "success": True, "opponent": opp, "enemy": opp,
        "battle": {"battle_type": "bot_pvp", "distance": battle.distance, "wind": round(battle.wind, 1), "turn": battle.turn,
                   "player_hp": player.current_hp, "enemy_hp": enemy.current_hp,
                   "player_rage": player.rage, "enemy_rage": enemy.rage}})

@app.route('/api/bot_battle/player_act', methods=['POST'])
def api_bot_battle_player_act():
    if not battle or getattr(battle, "battle_type", "") != "bot_pvp":
        return jsonify({"ok": False, "error": "no bot battle"}), 400
    return api_player_act()

@app.route('/api/bot_battle/ai_act', methods=['POST'])
def api_bot_battle_ai_act():
    if not battle or getattr(battle, "battle_type", "") != "bot_pvp":
        return jsonify({"ok": False, "error": "no bot battle"}), 400
    return api_ai_act()

@app.route('/api/player_act',methods=['POST'])
def api_player_act():
    global battle,player,enemy,battle_over
    if not battle:return jsonify({"error":"no battle"})
    d=request.get_json(force=True,silent=True) or {};auto=d.get("auto",False);ultimate=d.get("ultimate",False)
    if ultimate and player.rage>=100:
        dmg,msg=battle.ultimate();angle=power=None;fid=None
    elif auto:
        dmg,msg,angle,power,fid=battle.player_act(0,0,auto=True)
    else:
        dmg,msg,angle,power,fid=battle.player_act(d.get("angle",45),d.get("power",80),d.get("formula"))
    over=battle.is_over()
    resp={"ok":True,"dmg":dmg,"msg":msg,"log":battle.log,
          "player_hp":player.current_hp,"enemy_hp":max(0,enemy.current_hp),
          "player_rage":player.rage,"over":over,"battle_type":getattr(battle,"battle_type","normal")}
    if auto:resp["auto_angle"]=angle;resp["auto_power"]=power;resp["auto_formula"]=fid
    # 敌人台词
    enemy_type=getattr(enemy,'_type','capoo')
    if over=="victory":resp["enemy_line"]=random_line("defeat",enemy_type)
    elif over=="defeat":resp["enemy_line"]=random_line("victory",enemy_type)
    elif dmg>50:resp["enemy_line"]=random_line("hit",enemy_type)
    if over:
        if over=="victory":
            player.wins+=1;player.battles+=1
            resp["reward"]=settle_battle_reward(over)
        elif over=="defeat":
            player.battles+=1
            resp["reward"]=settle_battle_reward(over)
        restore_player_after_battle()
        resp["player_hp"]=player.current_hp
        resp["healed_after_battle"]=True
        save_p()
    return jsonify(resp)

@app.route('/api/ai_act',methods=['POST'])
def api_ai_act():
    global battle,player,enemy,battle_over
    try:
        print(f"[AI_ACT] called | battle={'exists' if battle else 'None'} | enemy={enemy.name if enemy else 'None'}")
        if not battle:return jsonify({"ok":True,"dmg":0,"msg":"无战斗","player_hp":player.current_hp if player else 0,"enemy_hp":0,"over":None,"enemy_line":"","error":"no battle"})
        enemy_type=getattr(enemy,'_type','capoo')
        resp_line=random_line("attack",enemy_type)
        dmg,msg=battle.ai_act()
        over=battle.is_over()
        print(f"[AI_ACT] dmg={dmg} | over={over} | player_hp={player.current_hp}/{player.maxhp} | enemy_hp={enemy.current_hp}/{enemy.maxhp}")
        resp={"ok":True,"dmg":dmg,"msg":msg,"log":battle.log,
              "player_hp":player.current_hp,"enemy_hp":max(0,enemy.current_hp),
              "enemy_rage":enemy.rage,"over":over,"enemy_line":resp_line,"battle_type":getattr(battle,"battle_type","normal")}
        if over:
            if over=="victory":
                player.wins+=1;player.battles+=1
                resp["reward"]=settle_battle_reward(over)
            elif over=="defeat":
                player.battles+=1
                resp["reward"]=settle_battle_reward(over)
            resp["enemy_line"]=random_line("defeat" if over=="victory" else "victory",enemy_type)
            restore_player_after_battle()
            resp["player_hp"]=player.current_hp
            resp["healed_after_battle"]=True
            save_p()
        return jsonify(resp)
    except Exception as ex:
        import traceback
        traceback.print_exc()
        return jsonify({"ok":True,"dmg":0,"msg":f"AI异常: {ex}","player_hp":player.current_hp if player else 0,"enemy_hp":0,"over":None,"enemy_line":"","error":str(ex)})

@app.route('/api/player_data')
def api_player_data():return jsonify(pd()if player else{})

@app.route('/api/weapons')
def api_weapons():
    ws=[]
    for wid,w in WEAPONS.items():
        if w.quality.value>SHOP_MAX_WEAPON_QUALITY.value or w.price<=0:
            continue
        price=shop_price(w)
        ws.append({"id":wid,"name":w.name,"quality":w.quality.value,"quality_tag":Q_TAGS[w.quality.value],
            "color":Q_COLORS[w.quality.value],"base_damage":w.base_damage,"atk":w.atk,"defense":w.defense,
            "agility":w.agility,"luck":w.luck,"angle":w.angle,"desc":w.desc,"price":price,"base_price":w.price,"level_req":w.level_req,
            "icon":w.icon,"special_effect":w.special_effect,"family":w.family,"weapon_type":w.weapon_type,
            "pit_radius":w.pit_radius,"pit_depth":w.pit_depth,"projectile_count":w.projectile_count})
    ws.sort(key=lambda x:(x["quality"],x["price"]))
    return jsonify({"weapons":ws,"equipped":player.weapon_id if player else None,
        "coins":player.coins if player else 0,"level":player.level if player else 1})

@app.route('/api/equipments')
def api_equipments():
    try:
        es=[]
        for eid,e in EQUIPMENTS.items():
            if e.quality.value>SHOP_MAX_EQUIP_QUALITY.value or e.price<=0:
                continue
            price=shop_price(e)
            es.append({"id":eid,"name":e.name,"slot":str(e.slot.value),"quality":e.quality.value,
                "quality_tag":Q_TAGS[e.quality.value],"color":Q_COLORS[e.quality.value],
                "defense":e.defense,"hp_bonus":e.hp_bonus,"atk_bonus":e.atk_bonus,
                "agi_bonus":e.agi_bonus,"luk_bonus":e.luk_bonus,
                "desc":e.desc,"price":price,"base_price":e.price,"level_req":e.level_req})
        es.sort(key=lambda x:(x["quality"],x["price"]))
        eq_map={}
        if player:
            for slot,attr in[("helmet",player.equip_helmet),("chest",player.equip_chest),("boots",player.equip_boots),("accessory",player.equip_accessory)]:
                eq_map[slot]=attr
        return jsonify({"equipments":es,"equipped":eq_map,"coins":player.coins if player else 0,"level":player.level if player else 1})
    except Exception as ex:
        return jsonify({"error":str(ex)}), 500

@app.route('/api/buy_weapon',methods=['POST'])
def api_buy_weapon():
    global player
    d=request.get_json(force=True,silent=True) or {};wid=d.get("weapon_id")
    if wid not in WEAPONS:return jsonify({"ok":False,"msg":"武器不存在"})
    w=WEAPONS[wid]
    if w.quality.value>SHOP_MAX_WEAPON_QUALITY.value or w.price<=0:
        return jsonify({"ok":False,"msg":"神器及以上武器不能用金币购买，请用70片以上武器碎片兑换，或通过副本/天使魔罐获取"})
    price=shop_price(w)
    if player.level<w.level_req:return jsonify({"ok":False,"msg":f"需要Lv.{w.level_req}"})
    if player.coins<price:return jsonify({"ok":False,"msg":f"金币不足({price}💰)"})
    if player.weapon_id==wid:return jsonify({"ok":False,"msg":"已经装备了"})
    player.coins-=price;player.add_weapon(wid);player.weapon_id=wid;save_p()
    return jsonify({"ok":True,"msg":f"装备了{w.name}！","player":pd()})

@app.route('/api/buy_equip',methods=['POST'])
def api_buy_equip():
    global player
    d=request.get_json(force=True,silent=True) or {};eid=d.get("equip_id")
    if eid not in EQUIPMENTS:return jsonify({"ok":False,"msg":"装备不存在"})
    eq=EQUIPMENTS[eid]
    if eq.quality.value>SHOP_MAX_EQUIP_QUALITY.value or eq.price<=0:
        return jsonify({"ok":False,"msg":"该品质装备不能用金币购买，请通过碎片合成、副本掉落或魔罐获取"})
    price=shop_price(eq)
    if player.level<eq.level_req:return jsonify({"ok":False,"msg":f"需要Lv.{eq.level_req}"})
    if player.coins<price:return jsonify({"ok":False,"msg":f"金币不足({price}💰)"})
    player.coins-=price;player.add_equip(eid);player.equip_item(eid);save_p()
    return jsonify({"ok":True,"msg":f"装备了{eq.name}！","player":pd()})

# ═══ 背包 + 装备切换 ═══
@app.route('/api/inventory')
def api_inventory():
    """返回玩家背包中所有物品"""
    global player
    if not player:return jsonify({"weapons":[],"equipment":[]})
    wlist=[{"id":wid,"name":WEAPONS[wid].name,"quality":WEAPONS[wid].quality.value,"quality_tag":Q_TAGS[WEAPONS[wid].quality.value],"color":Q_COLORS[WEAPONS[wid].quality.value],"icon":WEAPONS[wid].icon,"equipped":player.weapon_id==wid} for wid in player.owned_weapons if wid in WEAPONS]
    elist=[{"id":eid,"name":EQUIPMENTS[eid].name,"slot":EQUIPMENTS[eid].slot.value,"quality":EQUIPMENTS[eid].quality.value,"quality_tag":Q_TAGS[EQUIPMENTS[eid].quality.value],"color":Q_COLORS[EQUIPMENTS[eid].quality.value],"equipped":eid in [player.equip_helmet,player.equip_chest,player.equip_boots,player.equip_accessory]} for eid in player.owned_equipment if eid in EQUIPMENTS]
    return jsonify({"weapons":wlist,"equipment":elist})

@app.route('/api/switch_weapon',methods=['POST'])
def api_switch_weapon():
    """切换装备的武器"""
    global player
    d=request.get_json(force=True,silent=True) or {};wid=d.get("weapon_id")
    if wid in WEAPONS and wid in player.owned_weapons:
        old_enhance = player.weapon_enhances.get(player.weapon_id, 0)
        new_enhance = player.weapon_enhances.get(wid, 0)
        if old_enhance > new_enhance:
            player.weapon_enhances[wid] = old_enhance
        player.weapon_id=wid;save_p()
        return jsonify({"ok":True,"msg":f"切换为{WEAPONS[wid].name}","player":pd()})
    return jsonify({"ok":False,"msg":"未拥有此武器"})

@app.route('/api/switch_equip',methods=['POST'])
def api_switch_equip():
    """切换装备"""
    global player
    d=request.get_json(force=True,silent=True) or {};eid=d.get("equip_id")
    if eid in EQUIPMENTS and eid in player.owned_equipment:
        player.equip_item(eid);save_p()
        return jsonify({"ok":True,"msg":f"装备了{EQUIPMENTS[eid].name}","player":pd()})
    return jsonify({"ok":False,"msg":"未拥有此装备"})

@app.route('/api/craft_weapon',methods=['POST'])
def api_craft_weapon():
    global player
    d=request.get_json(force=True,silent=True) or {};wid=d.get("weapon_id")
    if wid not in WEAPONS:return jsonify({"ok":False,"msg":"武器不存在"})
    w=WEAPONS[wid]
    if w.quality.value<=SHOP_MAX_WEAPON_QUALITY.value:
        return jsonify({"ok":False,"msg":"该武器可通过商店或副本掉落获取，不需要碎片合成"})
    need=fragment_need_for_quality(w.quality)
    have=player.weapon_fragments.get(wid,0)
    if have<need:return jsonify({"ok":False,"msg":f"{w.name}碎片不足，需要{need}片(当前{have}片)"})
    player.weapon_fragments[wid]=have-need;player.add_weapon(wid);save_p()
    return jsonify({"ok":True,"msg":f"合成了{w.name}！","player":pd()})

@app.route('/api/craftables')
def api_craftables():
    global player
    if not player:return jsonify({"weapons":[],"equipment":[]})
    weapons=[]
    for wid,w in WEAPONS.items():
        if w.quality.value>SHOP_MAX_WEAPON_QUALITY.value:
            need=fragment_need_for_quality(w.quality)
            have=player.weapon_fragments.get(wid,0)
            weapons.append({"id":wid,"name":w.name,"quality_tag":Q_TAGS[w.quality.value],
                "quality":w.quality.value,"color":Q_COLORS[w.quality.value],"icon":w.icon,"need":need,"have":have,"owned":wid in player.owned_weapons,
                "can":have>=need})
    equips=[]
    for eid,e in EQUIPMENTS.items():
        if e.quality.value>SHOP_MAX_EQUIP_QUALITY.value:
            need=fragment_need_for_quality(e.quality)
            have=player.equip_fragments.get(eid,0)
            equips.append({"id":eid,"name":e.name,"slot":e.slot.value,"quality_tag":Q_TAGS[e.quality.value],
                "quality":e.quality.value,"color":Q_COLORS[e.quality.value],"need":need,"have":have,"owned":eid in player.owned_equipment,
                "can":have>=need})
    return jsonify({"weapons":weapons,"equipment":equips,"weapon_fragments":player.weapon_fragments,
        "equip_fragments":player.equip_fragments})

@app.route('/api/craft_equip',methods=['POST'])
def api_craft_equip():
    global player
    d=request.get_json(force=True,silent=True) or {};eid=d.get("equip_id")
    if eid not in EQUIPMENTS:return jsonify({"ok":False,"msg":"装备不存在"})
    e=EQUIPMENTS[eid]
    if e.quality.value<=SHOP_MAX_EQUIP_QUALITY.value:
        return jsonify({"ok":False,"msg":"该装备可通过商店或副本掉落获取，不需要碎片合成"})
    need=fragment_need_for_quality(e.quality)
    have=player.equip_fragments.get(eid,0)
    if have<need:return jsonify({"ok":False,"msg":f"{e.name}碎片不足，需要{need}片(当前{have}片)"})
    player.equip_fragments[eid]=have-need;player.add_equip(eid);save_p()
    return jsonify({"ok":True,"msg":f"合成了{e.name}！","player":pd()})

# ═══ 新强化系统 ═══
@app.route('/api/enhance/info')
def api_enhance_info():
    global player
    if not player:return jsonify({"error":"no player"})
    info=player.enhance_info(player.weapon_id)
    # 补充Capoo GIFs
    import glob as _g
    gifs=[os.path.basename(g) for g in _g.glob(os.path.join(rp2("picture"),"enemy","*.gif"))]
    info["capoo_gifs"]=gifs[:10]
    return jsonify(info)

@app.route('/api/enhance',methods=['POST'])
def api_enhance():
    global player
    d=request.get_json(force=True,silent=True) or {}
    wid=d.get("weapon_id",player.weapon_id)
    small=d.get("small",0);medium=d.get("medium",0);large=d.get("large",0)
    super_stone=d.get("super",0);angel_blessing=d.get("angel_blessing",0)
    result=player.do_enhance(wid,small,medium,large,super_stone,angel_blessing)
    save_p()
    if result.get("enhance_ok"):
        # 成功时随机选Capoo GIF
        import glob as _g
        gifs=[os.path.basename(g) for g in _g.glob(os.path.join(rp2("picture"),"enemy","*.gif"))]
        if gifs and result.get("celebration","normal") in ("great","legend","mythic"):
            result["capoo_gif"]=random.choice(gifs)
    result["player"]=pd()
    return jsonify(result)

# ═══ 天使魔罐 API ═══
@app.route('/api/angel_can/info')
def api_angel_can_info():
    global player
    if not player:return jsonify({"error":"no player"})
    st=player.angel_stats
    return jsonify({"ok":True,"items":{"angel_pot":player.angel_pot,"angel_hammer":player.angel_hammer,
        "silver_pot":player.silver_pot,"gold_pot":player.gold_pot,"fragment":player.magic_can_fragment,
        "blessing":player.angel_blessing_stone},
        "stats":st,"progress":{"silver_need":10-st["angel_open"]%10,"gold_need":100-st["angel_open"]%100}})

@app.route('/api/angel_can/buy_hammers',methods=['POST'])
def api_angel_can_buy_hammers():
    global player
    if not player:return jsonify({"ok":False,"error":"no player"})
    if player.coins<500:return jsonify({"ok":False,"error":"金币不足，需要500金币"})
    player.coins-=500;player.angel_hammer+=4;save_p()
    return jsonify({"ok":True,"player":pd(),"bought":{"angel_hammer":4,"coins":500}})

@app.route('/api/angel_can/exchange_fragment',methods=['POST'])
def api_angel_can_exchange_fragment():
    global player
    if not player:return jsonify({"ok":False,"error":"no player"})
    if player.magic_can_fragment<50:return jsonify({"ok":False,"error":"魔罐碎片不足，需要50个"})
    player.magic_can_fragment-=50;player.angel_pot+=1;save_p()
    return jsonify({"ok":True,"player":pd(),"exchanged":{"fragment":50,"angel_pot":1}})

@app.route('/api/angel_can/open',methods=['POST'])
def api_angel_can_open():
    global player
    try:
        d=request.get_json(force=True,silent=True) or {}
        can_type=d.get("can_type","angel");count=min(10,max(1,d.get("count",1)))
        cost_hammer=count*4
        if can_type=="angel":
            if player.angel_pot<count:return jsonify({"ok":False,"error":"天使魔罐不足"})
            if player.angel_hammer<cost_hammer:return jsonify({"ok":False,"error":"天使魔锤不足"})
            player.angel_pot-=count;player.angel_hammer-=cost_hammer
        elif can_type=="silver":
            if player.silver_pot<count:return jsonify({"ok":False,"error":"华丽的银罐不足"})
            if player.angel_hammer<cost_hammer:return jsonify({"ok":False,"error":"天使魔锤不足"})
            player.silver_pot-=count;player.angel_hammer-=cost_hammer
        elif can_type=="gold":
            if player.gold_pot<count:return jsonify({"ok":False,"error":"耀眼的金罐不足"})
            if player.angel_hammer<cost_hammer:return jsonify({"ok":False,"error":"天使魔锤不足"})
            player.gold_pot-=count;player.angel_hammer-=cost_hammer
        else:return jsonify({"ok":False,"error":"未知魔罐类型"})
        
        all_rewards=[];best_rarity="common"
        for _ in range(count):
            rewards,rarity=roll_angel_can(can_type)
            all_rewards.append({"rarity":rarity,"items":rewards})
            if rarity in ("legend","mythic"):best_rarity=rarity
            elif rarity=="epic" and best_rarity!="legend" and best_rarity!="mythic":best_rarity=rarity
            # 发放奖励
            for rw in rewards:
                if rw["type"]=="weapon":player.add_weapon(rw["id"])
                elif rw["type"]=="equip":player.add_equip(rw["id"])
                elif rw["type"]=="coins":player.coins+=rw["n"]
                elif rw["type"]=="stone":player.add_stone(rw["tier"],rw["n"])
                elif rw["type"]=="fragment":player.magic_can_fragment+=rw["n"]
                elif rw["type"]=="blessing":player.angel_blessing_stone+=rw["n"]
                elif rw["type"]=="weapon_fragments":
                    fid=rw.get("frag_id","")
                    if fid:player.weapon_fragments[fid]=player.weapon_fragments.get(fid,0)+rw["n"]
                elif rw["type"]=="equip_fragments":
                    fid=rw.get("frag_id","")
                    if fid:player.equip_fragments[fid]=player.equip_fragments.get(fid,0)+rw["n"]
            # 更新统计
            st=player.angel_stats
            st["angel_open"]=st.get("angel_open",0)+1;st["total"]=st.get("total",0)+1
            if rarity in ("epic","legend","mythic"):st["since_epic"]=0
            else:st["since_epic"]=st.get("since_epic",0)+1
            if rarity in ("legend","mythic"):st["since_legend"]=0
            else:st["since_legend"]=st.get("since_legend",0)+1
        
        # 保底赠送（用更新后的值）
        bonus_silver=0;bonus_gold=0
        total_opens = player.angel_stats.get("angel_open",0)
        if total_opens % 10 == 0 and total_opens > 0: bonus_silver=1; player.silver_pot+=1
        if total_opens % 100 == 0 and total_opens > 0: bonus_gold=1; player.gold_pot+=1
        
        save_p()
        # 真人玩家获得传说/神话奖励时，同步到公屏聊天
        if best_rarity in ("legend","mythic"):
            chat_log = load_chat_log()
            chat_log.append({"time": _dt.datetime.now().isoformat(), "name": player.name,
                "channel": "world", "msg": f"🎉 恭喜【{player.name}】开启天使魔罐，获得{best_rarity}奖励！", "is_bot": False})
            save_chat_log(chat_log[-100:])
        return jsonify({"ok":True,"opened":count,"consumed":{"hammer":cost_hammer,"pot":count},
            "rewards":all_rewards,"best_rarity":best_rarity,"bonus":{"silver":bonus_silver,"gold":bonus_gold},
            "stats":player.angel_stats,"player":pd()})
    except Exception as ex:
        import traceback;traceback.print_exc()
        return jsonify({"ok":False,"error":str(ex)})

@app.route('/api/dungeons')
def api_dungeons():
    """副本列表 — 使用统一战力引擎"""
    from enemy_engine import recommended_power_by_tier
    ds=[]
    for d in DUNGEONS:
        # 推算推荐战力: lv越高越强
        rec_power = d.get("recommended_power") or max(2000, d["lv"]*600 + d["lv"]**2*15)
        unlocked = False
        if player:
            try: unlocked = player.power >= rec_power
            except: unlocked = False
        ds.append({"id":d["id"],"name":d["name"],"lv":d["lv"],"desc":d["desc"],
            "stages":len(d["stages"]),"unlocked":unlocked,
            "recommended_power":rec_power,
            "rewards":{"coins":d["rw"]["coins"],"exp":d["rw"]["exp"]},
            "drops":d.get("drops",[])})  # 包含掉落表
    return jsonify({"dungeons":ds})

@app.route('/api/start_dungeon',methods=['POST'])
def api_start_dungeon():
    global player,battle,enemy,battle_over
    d=request.get_json(force=True,silent=True) or {};did=d.get("dungeon_id")
    dg=next((d for d in DUNGEONS if d["id"]==did),None)
    if not dg:return jsonify({"ok":False,"msg":"副本不存在"})
    cp_req = max(500, dg["lv"]*350 + dg["lv"]**2*3)
    if player.power < cp_req:return jsonify({"ok":False,"msg":f"战力不足，需要{cp_req}战斗力"})
    player.init_battle()
    st=dg["stages"][0]
    enemy=gen_kiwi_enemy(player.level,st["d"],st.get("boss",False));enemy.init_battle()
    battle=BattleEngine(player,enemy);battle_over=None
    return jsonify({"ok":True,"dungeon":dg,"current_stage":0,"enemy":{
        "name":enemy.name,"level":enemy.level,"maxhp":enemy.maxhp,
        "atk":enemy.atk,"defense":enemy.defense,"weapon_name":enemy.weapon.name if enemy.weapon else"无",
        "gif":getattr(enemy,'_gif',''),"type":getattr(enemy,'_type','kiwi'),
        "enter_line":random_line("enter","kiwi")
    },"battle":{"distance":battle.distance,"wind":round(battle.wind,1),"turn":battle.turn,
        "player_hp":player.current_hp,"enemy_hp":enemy.current_hp,
        "player_rage":player.rage,"enemy_rage":enemy.rage}})

@app.route('/api/dungeon_drops',methods=['POST'])
def api_dungeon_drops():
    """副本掉落结算 — 基于drop表+爆率，返回5张卡"""
    global player
    d=request.get_json(force=True,silent=True) or {};did=d.get("dungeon_id")
    dg=next((d for d in DUNGEONS if d["id"]==did),None)
    if not dg:return jsonify({"ok":False})
    rw=dg["rw"];real_drops=[]
    # 强化石(固定掉落)
    sn=random.randint(*rw["stone_n"]);player.add_stone(rw["stone"],sn)
    real_drops.append({"type":"stone","tier":rw["stone"],"name":ENHANCE_STONE_TIERS[rw["stone"]],"n":sn,"rarity":"common"})
    hammer_n=random.randint(2,6);player.angel_hammer+=hammer_n
    real_drops.append({"type":"angel_hammer","name":"天使魔锤","n":hammer_n,"rarity":"common","icon":"🔨"})
    frag_n=random.randint(6,18);player.magic_can_fragment+=frag_n
    real_drops.append({"type":"fragment","name":"魔罐碎片","n":frag_n,"rarity":"rare","icon":"🧩"})
    wf=random.randint(3,10);ef=random.randint(3,10)
    wpool=[wid for wid,w in WEAPONS.items() if w.quality.value>SHOP_MAX_WEAPON_QUALITY.value]
    epool=[eid for eid,e in EQUIPMENTS.items() if e.quality.value>SHOP_MAX_EQUIP_QUALITY.value]
    if wpool:
        wid=random.choice(wpool);w=WEAPONS[wid]
        player.weapon_fragments[wid]=player.weapon_fragments.get(wid,0)+wf
        real_drops.append({"type":"weapon_fragments","name":f"{w.icon} {w.name}·碎片","frag_id":wid,"n":wf,"rarity":"rare","icon":w.icon})
    if epool:
        eid=random.choice(epool);e=EQUIPMENTS[eid]
        player.equip_fragments[eid]=player.equip_fragments.get(eid,0)+ef
        real_drops.append({"type":"equip_fragments","name":f"🛡️ {e.name}·碎片","frag_id":eid,"n":ef,"rarity":"rare","icon":"🛡️"})
    if random.random() < max(0.08, min(0.35, dg.get("lv",1)/100)):
        player.angel_pot+=1
        real_drops.append({"type":"angel_pot","name":"天使魔罐","n":1,"rarity":"epic","icon":"🏺"})
    # 基于drop表的概率掉落
    for drop_entry in dg.get("drops",[]):
        if random.random() < drop_entry["rate"]:
            item_id = random.choice(drop_entry["ids"])
            if drop_entry["type"] == "weapon" and item_id in WEAPONS:
                w = WEAPONS[item_id]
                rarity_label = "mythic" if w.quality==Quality.MYTHIC else ("legend" if w.quality==Quality.LEGEND else ("epic" if w.quality==Quality.DIVINE else ("rare" if w.quality==Quality.EXTREME else "common")))
                real_drops.append({"type":"weapon","id":item_id,"name":w.name,"quality":w.quality.value,"quality_tag":Q_TAGS[w.quality.value],"icon":w.icon,"special_effect":w.special_effect,"rarity":rarity_label})
            elif drop_entry["type"] == "equip" and item_id in EQUIPMENTS:
                eq = EQUIPMENTS[item_id]
                rarity_label = "epic" if eq.quality==Quality.DIVINE else ("rare" if eq.quality==Quality.EXTREME else "common")
                real_drops.append({"type":"equip","id":item_id,"name":eq.name,"slot":eq.slot.value,"quality":eq.quality.value,"quality_tag":Q_TAGS[eq.quality.value],"rarity":rarity_label})
    
    # 生成5张卡：填充到恰好5张，空缺用金币/经验补
    cards = []
    bonus_items = [
        {"type":"coins","name":"金币袋","n":random.randint(50,200),"rarity":"common","icon":"💰"},
        {"type":"exp","name":"经验书","n":random.randint(30,150),"rarity":"common","icon":"⭐"},
        {"type":"stone","name":"小强化石","n":random.randint(1,2),"rarity":"common","icon":"💎"},
    ]
    # 先放真实掉落；真实掉落超过5个时也只展示5张，保持“5选2”的规则稳定。
    random.shuffle(real_drops)
    real_drops = real_drops[:5]
    for dp in real_drops:
        cards.append(dp)
    # 补到5张
    while len(cards) < 5:
        bonus = random.choice(bonus_items).copy()
        # 避免重复金币/经验卡过多
        if bonus["type"] == "coins": player.coins += bonus["n"]
        elif bonus["type"] == "exp": player.gain_exp(bonus["n"])
        elif bonus["type"] == "stone": player.add_stone("small", bonus["n"])
        bonus["flipped"] = False
        cards.append(bonus)
    # 洗牌
    random.shuffle(cards)
    cards = cards[:5]
    for c in cards: c["flipped"] = False
    
    coins_reward=random.randint(*rw["coins"])
    exp_reward=random.randint(*rw["exp"])
    player.coins+=coins_reward
    player.gain_exp(exp_reward)
    save_p()
    return jsonify({"ok":True,"cards":cards,"coins_reward":coins_reward,"exp_reward":exp_reward,"player":pd()})

@app.route('/api/equip_drop',methods=['POST'])
def api_equip_drop():
    """装备掉落物品 — 加入背包"""
    global player
    d=request.get_json(force=True,silent=True) or {};eid=d.get("equip_id");wid=d.get("weapon_id")
    if eid in EQUIPMENTS:player.add_equip(eid);player.equip_item(eid)
    if wid in WEAPONS:player.add_weapon(wid);player.weapon_id=wid
    save_p()
    return jsonify({"ok":True,"player":pd()})

def run_server():
    import os as _os
    is_cloud = 'RENDER' in _os.environ
    port = int(_os.environ.get('PORT', 19999)) if is_cloud else pick_local_port(19999)
    if not is_cloud:
        webbrowser.open(f'http://127.0.0.1:{port}')
    # 云端用 waitress 生产服务器，本地用 Flask dev server
    if is_cloud:
        try:
            from waitress import serve
            print(f"DDTank 云端启动: http://0.0.0.0:{port}")
            serve(app, host='0.0.0.0', port=port)
        except ImportError:
            app.run(host='0.0.0.0', port=port, debug=False)
    else:
        app.run(host='127.0.0.1', port=port, debug=False)

# ═══════════════ 星蚀试炼塔 (v2: 难度选择→地图→战斗) ═══════════════
from rogue_engine import register_rogue_routes, ROGUE_MIN_POWER, ROGUE_MAX_POWER, ROGUE_CARDS, ROGUE_FLOORS
_player_ref = type('_Ref',(),{'v':player})()
register_rogue_routes(app, _player_ref, save_p, pd)

if __name__=='__main__':
    # ═══ 初始化数据库（PostgreSQL or local fallback） ═══
    print("=" * 50)
    print(f"[STARTUP] DATABASE_URL={'SET' if DATABASE_URL else 'NOT SET'}")
    init_db()
    print(f"[STARTUP] Storage: {'PostgreSQL' if use_pg else 'local saves/auth.json'}")
    print("=" * 50)
    random.seed();ensure_gifs()
    # 自动生成bots
    data = load_bot_profiles()
    cleaned = [b for b in data.get("bots",[]) if not is_test_name(b.get("display_name",""))]
    if len(cleaned) < 500:
        print(f"生成AI玩家... (当前{len(cleaned)}个, 目标500+)")
        # 清理旧测试数据
        data["bots"] = cleaned
        save_bot_profiles(data)
        generate_bots(500 - len(cleaned))
    # 自动刷新排行榜
    refresh_leaderboard()
    # ═══ 后台公屏聊天：每分钟1-2条bot消息 ═══
    def chat_simulator_loop():
        import time as _time
        while True:
            try:
                # 每分钟生成1-2条bot聊天
                n = random.randint(1, 2)
                for _ in range(n):
                    simulate_bot_actions(steps=1)
                _time.sleep(60)  # 每分钟一次
            except Exception:
                _time.sleep(30)
    chat_thread = threading.Thread(target=chat_simulator_loop, daemon=True)
    chat_thread.start()
    print("公屏聊天模拟器已启动 (每分钟1-2条消息)")
    import os as _os
    is_cloud = 'RENDER' in _os.environ
    port = int(_os.environ.get('PORT', 19999)) if is_cloud else pick_local_port(19999)
    host = '127.0.0.1' if not is_cloud else '0.0.0.0'
    print(f"GiguaT 启动中... http://{host}:{port}")
    run_server()


