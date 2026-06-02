"""
统一敌人数值引擎 — 所有敌人(人机练习/真人对战NPC/副本/试炼塔)共用
公式: power = max_hp*0.18 + attack*3.2 + defense*2.2 + armor*2.5 + agility*1.3 + luck*1.8 + damage*2.8
"""
import random, math

# ═══ 战斗力曲线 ═══
ROGUE_MIN_POWER = 2000
ROGUE_MAX_POWER = 120000

def recommended_power_by_tier(tier):
    """1-20阶指数曲线, 1阶~2000, 20阶~120000"""
    t = max(1, min(20, int(tier)))
    return round(ROGUE_MIN_POWER * (ROGUE_MAX_POWER / ROGUE_MIN_POWER) ** ((t - 1) / 19))

# ═══ 反向计算: 从目标战力推导敌人属性 ═══
def enemy_stats_from_power(target_power):
    """
    按分配比例反推属性:
    生命20% 攻击20% 防御13% 护甲12% 敏捷5% 幸运5% 伤害25%
    返回完整的敌人属性dict
    """
    hp = round(target_power * 0.20 / 0.18)
    attack = round(target_power * 0.20 / 3.2)
    defense = round(target_power * 0.13 / 2.2)
    armor = round(target_power * 0.12 / 2.5)
    agility = round(target_power * 0.05 / 1.3)
    luck = round(target_power * 0.05 / 1.8)
    damage = round(target_power * 0.25 / 2.8)
    
    return {
        "hp": hp, "max_hp": hp, "current_hp": hp,
        "attack": attack, "defense": defense, "armor": armor,
        "agility": agility, "luck": luck, "damage": damage,
        "weapon_damage": damage,
    }

def calc_enemy_power(stats):
    """根据属性计算战斗力"""
    return round(
        stats.get("max_hp", stats.get("hp", 0)) * 0.18 +
        stats.get("attack", 0) * 3.2 +
        stats.get("defense", 0) * 2.2 +
        stats.get("armor", 0) * 2.5 +
        stats.get("agility", 0) * 1.3 +
        stats.get("luck", 0) * 1.8 +
        stats.get("damage", stats.get("weapon_damage", 0)) * 2.8
    )

# ═══ 类型倍率 ═══
ENEMY_TYPE_MULTIPLIERS = {
    "normal":    {"hp": 1.00, "attack": 1.00, "defense": 1.00, "armor": 1.00, "damage": 1.00, "luck": 1.00},
    "elite":     {"hp": 1.35, "attack": 1.18, "defense": 1.15, "armor": 1.15, "damage": 1.15, "luck": 1.10},
    "boss":      {"hp": 1.85, "attack": 1.30, "defense": 1.25, "armor": 1.25, "damage": 1.25, "luck": 1.15},
    "final_boss":{"hp": 2.80, "attack": 1.55, "defense": 1.45, "armor": 1.45, "damage": 1.45, "luck": 1.25},
}

def generate_enemy_by_power(target_power, enemy_type="normal", mode="pve", name=None):
    """
    统一敌人生成器
    target_power: 目标战斗力
    enemy_type: normal/elite/boss/final_boss
    mode: pve/dungeon/rogue
    name: 敌人名称
    """
    stats = enemy_stats_from_power(target_power)
    mult = ENEMY_TYPE_MULTIPLIERS.get(enemy_type, ENEMY_TYPE_MULTIPLIERS["normal"])
    
    hp = round(stats["hp"] * mult["hp"])
    attack = round(stats["attack"] * mult["attack"])
    defense = round(stats["defense"] * mult["defense"])
    armor = round(stats["armor"] * mult["armor"])
    agility = stats["agility"]  # 敏捷不缩放
    luck = round(stats["luck"] * mult.get("luck", 1.0))
    damage = round(stats["damage"] * mult["damage"])
    
    result = {
        "hp": hp, "max_hp": hp, "current_hp": hp,
        "attack": attack, "defense": defense, "armor": armor,
        "agility": agility, "luck": luck, "damage": damage,
        "weapon_damage": damage,
        "power": calc_enemy_power({"max_hp": hp, "attack": attack, "defense": defense,
                                     "armor": armor, "agility": agility, "luck": luck, "damage": damage}),
        "enemy_type": enemy_type, "mode": mode,
        "name": name or f"{enemy_type}_{random.randint(100,999)}",
        # kiwi GIF
        "sprite": "/picture/enemy/default.gif",
        "hue": random.randint(0, 359),
        "variant": enemy_type,
        # 技能
        "skills": [],
    }
    return result

# ═══ 人机练习敌人 ═══
def generate_practice_enemy(player_power, difficulty="normal"):
    """根据玩家战力生成人机练习敌人"""
    diff_mult = {"easy": 0.70, "normal": 0.90, "hard": 1.10, "nightmare": 1.30}
    target_power = round(player_power * diff_mult.get(difficulty, 0.90))
    enemy_type = "elite" if difficulty in ("hard", "nightmare") else "normal"
    result = generate_enemy_by_power(target_power, enemy_type, "practice")
    result["difficulty"] = difficulty
    result["difficulty_mult"] = diff_mult.get(difficulty, 0.90)
    # 奖励倍率
    reward_mult = {"easy": 0.6, "normal": 1.0, "hard": 1.5, "nightmare": 2.5}
    result["reward_mult"] = reward_mult.get(difficulty, 1.0)
    return result

# ═══ 真人对战NPC ═══
def generate_pvp_bot(player_power, bot_rank="matched"):
    """根据玩家战力生成真人对战NPC"""
    rank_mult = {"weak": 0.85, "matched": 1.00, "strong": 1.15, "champion": 1.35}
    target_power = round(player_power * rank_mult.get(bot_rank, 1.00))
    result = generate_enemy_by_power(target_power, "normal", "pvp")
    result["bot_rank"] = bot_rank
    result["rank_mult"] = rank_mult.get(bot_rank, 1.00)
    return result

# ═══ 副本敌人 ═══
def generate_dungeon_enemy(recommended_power, enemy_type="normal"):
    """根据副本推荐战力生成副本敌人"""
    if enemy_type == "boss":
        target_power = round(recommended_power * 1.30)
    elif enemy_type == "elite":
        target_power = round(recommended_power * 1.10)
    else:
        target_power = round(recommended_power * 0.95)
    result = generate_enemy_by_power(target_power, enemy_type, "dungeon")
    result["recommended_power"] = recommended_power
    return result

# ═══ 星蚀试炼塔敌人 ═══
def generate_rogue_enemy(tier, node_type="monster", completed_nodes=0):
    """根据试炼塔难度级别和节点类型生成敌人"""
    base_power = recommended_power_by_tier(tier)
    node_mult = {"monster": 0.95, "elite": 1.30, "boss": 1.80, "final_boss": 2.60}
    progress_mult = 1 + completed_nodes * 0.05
    target_power = round(base_power * node_mult.get(node_type, 0.95) * progress_mult)
    
    enemy_type = "final_boss" if node_type == "final_boss" else (
        "boss" if node_type == "boss" else ("elite" if node_type == "elite" else "normal"))
    
    result = generate_enemy_by_power(target_power, enemy_type, "rogue")
    result["tier"] = tier
    result["node_type"] = node_type
    result["base_power"] = base_power
    result["progress_mult"] = progress_mult
    return result
