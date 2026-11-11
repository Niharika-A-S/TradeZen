"""Bot trader definitions and personality cards for TradeZen."""
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List


class BotPersonality(str, Enum):
    DISCIPLINED = "Disciplined"
    OVERTRADER = "Overtrader"
    REVENGE_TRADER = "RevengeTrader"
    STOP_LOSS_IGNORER = "StopLossIgnorer"
    FOMO_CHASER = "FomoChaser"


@dataclass
class BotConfig:
    bot_id: int
    name: str
    personality: BotPersonality
    initial_capital: float = 10_00_000.0
    rules: Dict[str, Any] = field(default_factory=lambda: {
        "max_trades_per_day": 5,
        "max_risk_per_trade_pct": 2.0,
        "require_stop_loss": True,
        "max_consecutive_losses": 3,
    })


def create_default_bots(seed: int = 42) -> List[BotConfig]:
    """Creates the 30 programmed bots: 5 personalities x 6 bots each.
    
    Randomizes bot-specific rule limits within realistic ranges using a deterministic seed:
      - max_trades_per_day: 2 to 12
      - max_risk_per_trade_pct: 0.5 to 5.0
      - max_consecutive_losses: 2 to 5
    """
    rng = random.Random(seed)
    bots: List[BotConfig] = []

    personality_specs = [
        (BotPersonality.DISCIPLINED, "Disciplined"),
        (BotPersonality.OVERTRADER, "Overtrader"),
        (BotPersonality.REVENGE_TRADER, "RevengeTrader"),
        (BotPersonality.STOP_LOSS_IGNORER, "StopLossIgnorer"),
        (BotPersonality.FOMO_CHASER, "FomoChaser"),
    ]

    bot_id = 1
    for p_enum, p_name in personality_specs:
        for i in range(1, 7):
            rules = {
                "max_trades_per_day": rng.randint(2, 12),
                "max_risk_per_trade_pct": round(rng.uniform(0.5, 5.0), 1),
                "max_consecutive_losses": rng.randint(2, 5),
                "require_stop_loss": False if p_enum == BotPersonality.STOP_LOSS_IGNORER else True,
            }
            bots.append(BotConfig(
                bot_id=bot_id,
                name=f"{p_name}_{i}",
                personality=p_enum,
                rules=rules
            ))
            bot_id += 1

    return bots


class ProgrammedBot:
    """Encapsulates the state and decision-making logic of a bot during simulation."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.bot_id = config.bot_id
        self.name = config.name
        self.personality = config.personality
        self.capital = config.initial_capital
        self.rules = config.rules

    def __repr__(self) -> str:
        return f"<ProgrammedBot {self.name} ({self.personality.value}) ID={self.bot_id}>"
