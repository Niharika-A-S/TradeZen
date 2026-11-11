---
id: trading_knowledge_base
type: education
title: Trading Knowledge Base for Chatbot RAG
source_title: NSE & SEBI Investor Education Guidelines
source_url: https://investor.sebi.gov.in
evidence: exchange_and_regulatory_rules
last_reviewed: 2026-11-09
---

## Chatbot Role and Safety Rules
You are a trading education and behavioral-coaching assistant for beginner Indian stock-market traders.

Your job is to:
- Explain trading terms, order types, risk-management ideas, market rules, and investor protection.
- Help users reflect before trading: "What is your entry reason? What is your stop-loss? How much capital are you risking?"
- Remind users of their own pre-set rules, such as maximum risk per trade, maximum trades per day, and stop-loss discipline.
- Encourage users to pause and review when they show possible behavioral patterns such as revenge trading, overtrading, or ignoring stop-losses.

You must not:
- Recommend a specific stock, entry price, target, or "buy/sell now" decision.
- Claim that any trade will be profitable.
- Give personalized investment advice or act as a SEBI-registered investment adviser.
- Encourage excessive trading, leverage, or F&O speculation.
- Guarantee that a stop-loss will execute at the exact price.

Always add, when relevant: "This is educational information, not investment advice. Markets involve risk, and past behavior does not guarantee future results."

## Basic Market Concepts: Stock and Stock Market
A stock, also called a share or equity, represents a small ownership stake in a company. If you own shares of a company, you may benefit if the company grows and its share price rises, and you may also receive dividends if the company declares them. Buying a stock does not guarantee profit. Its price can fall below your purchase price, and you can lose money.

A stock market is a regulated place where buyers and sellers trade securities. In India, major exchanges include the National Stock Exchange (NSE) and BSE. NSE describes its trading system as an automated, order-driven market. Orders are matched based on best price first, then time priority for orders at the same price.

## Market Liquidity and Volatility
Liquidity means how easily you can buy or sell something without greatly affecting its price. A highly liquid stock has many active buyers and sellers. A low-liquidity stock may be harder to exit quickly, and the difference between the best buy and sell price may be wider. Liquidity risk is the difficulty of exiting a position quickly or at a fair price.

Volatility means how much and how quickly a price moves. High volatility can create opportunities, but it also increases the chance of rapid losses. A beginner should not treat volatility as a reason to trade more; it is a reason to use smaller position sizes and clearer exit plans.

## Orders and Execution: Market Order and Limit Order
An order is an instruction to your broker to buy or sell a security. It includes the instrument, side (buy or sell), quantity, order type, price if applicable, and validity. Orders that do not immediately match remain in the exchange's order book until they are matched or cancelled. NSE matches the best available buy order with the best available sell order.

A market order asks the broker/exchange to buy or sell immediately at the best available price. It is used when you want execution now and are less concerned about the exact price. In a fast-moving or low-liquidity stock, the final execution price may differ from the price you saw when placing the order. A market order prioritizes immediate execution, not a specific price.

A limit order lets you specify the maximum price you are willing to pay when buying, or the minimum price you are willing to accept when selling. A buy limit order executes at your limit price or lower. A sell limit order executes at your limit price or higher. A limit order provides price protection, but it may not execute at all if the market never reaches your price. For example, if you place a buy limit order at ₹100 and market price stays above ₹100, the order remains unfilled.

## Stop-Loss Order and Stop-Loss Limit Order Mechanics
A stop-loss order stays inactive until the market price reaches or crosses a trigger price. Once triggered, it is released into the regular order book. For a sell stop-loss, you place it below the current market price, triggering when the last traded price falls to or below the trigger price. For a buy stop-loss, you place it above current market price, triggering when the price rises to or exceeds the trigger price.

Important: A stop-loss order is not a guaranteed exit at your exact trigger price. After triggering, it may become a market or limit order, and rapid market movement can cause execution at a worse price. SEBI's combined risk-disclosure document warns that stop-loss and limit orders may not be effective during rapid market movements.

A stop-loss limit order has two prices:
1. Trigger price: The price that activates the order.
2. Limit price: The worst acceptable execution price after activation.
For example, owning a stock trading at ₹100 with trigger ₹95 and limit ₹94 will activate at ₹95 and try to sell at ₹94 or better. If the market crashes below ₹94 and no buyer accepts ₹94, the order may not execute. A stop-loss limit gives price control but may not fill in a sharp fall.

## Order Validity Types: Day, IOC, GTC, and GTD
A day order is valid only for the trading day on which it is placed. If it is not executed by the end of that day, it is automatically cancelled.

An Immediate or Cancel (IOC) order must be executed immediately; any portion that cannot be matched immediately is cancelled. Partial execution is possible (e.g. buying 100 shares where only 40 are available results in 40 executed and 60 cancelled).

GTC (Good Till Cancelled) orders remain active until cancelled, subject to exchange limits. GTD (Good Till Date) orders remain active until a specified date, then expire. GTC and GTD availability depends on current exchange and SEBI directives.

## Risk Management: Position Sizing and Capital Risk
Position size is the amount of money or number of shares you commit to one trade. A sound position size is based on the distance between entry and stop-loss, not on how confident you feel.

Formula: Position size = (Amount willing to risk) / (Entry price - Stop-loss price).
Example: Capital ₹1,00,000, risk per trade 1% (₹1,000), Entry ₹500, Stop-loss ₹480 (risk per share ₹20). Maximum shares = ₹1,000 / ₹20 = 50 shares.
Your position size should be decided before entry. If your stop-loss is ₹20 away and maximum loss is ₹1,000, maximum size is 50 shares, not a larger size because you feel confident.

Risk per trade is the maximum loss you are willing to accept if your stop-loss is hit. Beginner guideline: keep risk per trade small (0.5% to 1% of trading capital) so several losing trades will not seriously damage capital.

## Stop-Loss Discipline and Concentration Risk
Stop-loss discipline means deciding, before entering, the price at which your trade idea is no longer valid—and then following that plan. Stop-loss orders reduce risk but do not eliminate it. Key reflection prompts: "What is your stop-loss level, and what market condition would make your trade idea invalid?", "Is this stop-loss based on your original plan, or are you moving it because you do not want to accept a loss?", "If this trade hits your stop-loss, how much money will you lose, and is that within your rule?"

Concentration risk arises when too much capital is exposed to one stock, sector, or idea (for example 60% of capital in one stock). A large fall in that stock affects the portfolio much more severely than spread exposure.

## Behavioral Risks: Overtrading, Revenge Trading, and FOMO
Overtrading means placing more trades than your plan or emotional state supports. Common signs: taking many trades in a short period, entering without a clear reason, increasing position size after losses, trading to "recover" losses, and ignoring daily trade limits. Response: "You have placed several trades today. Before the next one, answer: Does this trade follow your written plan, or are you trying to recover a recent loss?"

Revenge trading is trying to win back money quickly after a loss, often through impulsive, oversized, or poorly planned trades driven by emotion. Response: "It looks like you may be trading to recover a recent loss. A better rule is to pause, review the previous trade, and return only when the next trade meets your plan."

FOMO (Fear Of Missing Out) occurs when entering because a stock is moving quickly or others talk about it. Response: "Before entering, ask: Would I take this trade if the stock had not already moved? What is my entry, stop-loss, and invalidation level?"

## Behavioral Coaching Rules Matrix
The platform uses these patterns to generate warnings:
1. Oversized position: Planned trade exceeds user's risk-per-trade rule -> "This trade exceeds your 1% risk rule. Reduce the quantity or reconsider the setup."
2. Missing stop-loss: User has no stop-loss or refuses to define one -> "What price would prove your trade idea wrong? Define that before entering."
3. Revenge trading: User re-enters immediately after a loss -> "You just had a loss. Pause and review: are you following your plan or trying to recover money?"
4. Overtrading: User exceeds daily trade limit -> "You have reached your planned trade limit for today. Consider stopping and reviewing the day."
5. FOMO entry: User wants to enter after a sharp move without a plan -> "The stock has already moved. What is your entry reason, stop-loss, and maximum risk?"
6. Stop-loss movement: User tries to move stop-loss farther away after entry -> "Moving a stop-loss farther away increases potential loss. Does this still fit your original risk plan?"
7. Concentration risk: New position exceeds portfolio/sector cap -> "This trade would make your exposure to one stock/sector higher than your chosen limit."

## F&O and Leverage Warnings
Derivatives are financial instruments whose value is derived from an underlying asset (stock, index, commodity, currency). Futures contracts are standardized agreements to buy or sell at a predetermined price on a future date. Options contracts give the buyer the right, but not obligation, to buy (call) or sell (put) at a predetermined price and date.

Why F&O is high risk: SEBI warns derivatives multiply profits and losses because upfront amount payable is small relative to underlying asset value. A wrong speculative decision can wipe out net worth. Derivatives are zero-sum (one participant's gain corresponds to another's loss). SEBI studies note that 9 out of 10 individual traders in equity F&O incurred net losses.

Margin is money/collateral maintained with the broker. Margin amplifies both gains and losses. Beginners should not use margin simply to trade larger positions.

## Investor Protection and SEBI Regulation
The Securities and Exchange Board of India (SEBI) is India's securities-market regulator protecting investors, regulating market intermediaries, and promoting orderly development.

A broker (trading member) is an intermediary providing exchange access. Every order is executed with the client's identity; orders without client ID are not accepted. Users must ensure: broker is SEBI-registered, understand brokerage/taxes/charges, never share passwords/OTPs, use official broker apps, and review contract notes.

In case of broker default, losses suffered on settled or closed-out derivative positions may be compensated from the Investor Protection Fund (IPF) under exchange bye-laws (not covering market trading losses).

Platforms must never provide stock tips ("Buy this", "This stock will rise", "Guaranteed profit"). Provide education, behavioral monitoring, and risk-rule alerts only.

## Ready-Made Chatbot Answers Guide
1. What is a stop-loss? A pre-set exit level designed to limit loss on a trade. For long positions, placed below entry price. Does not guarantee exact execution price during fast moves.
2. Should I move my stop-loss? Only move if part of a predefined plan (like trailing stop after trade moves in your favor). Do not move farther away to avoid accepting a loss.
3. What is a limit order? Lets you set maximum buying or minimum selling price. Protects price but may not execute if price isn't reached.
4. What is a market order? Used when immediate execution matters more than specific price; subject to slippage in fast markets.
5. How much should I risk per trade? Beginner guideline is 0.5% to 1% of trading capital. Risk amount, entry price, and stop-loss distance determine position size.
6. I lost money, should I trade again immediately? No. Stop for a cooling-off period, review setup and rule violations, check emotional state, return only when next trade meets written plan.
7. Is F&O good for beginners? No. F&O involves leverage, expiry, margin, rapid losses, and SEBI studies show 9 out of 10 individual traders lose money.

## Mandatory Regulatory Disclaimer
This chatbot provides educational and behavioral-risk information only. It does not provide investment advice, stock recommendations, or guarantees of profit. Trading in securities and derivatives involves risk, including the risk of loss. Stop-loss orders may not execute at the expected price during rapid market movements. Please make independent decisions and consult a SEBI-registered professional where appropriate.

## Metadata Sources and Reference Citations
Sources to cite in RAG metadata:
- NSE Trading System (order types, stop-loss mechanics, order matching): https://www.nseindia.com/products/content/equities/equities/trading_system.htm
- SEBI Investor - Understanding Derivatives: https://investor.sebi.gov.in/understanding_derivatives.html
- SEBI FAQ on Equity and Currency Derivatives: https://www.sebi.gov.in/sebi_data/docfiles/20621_t.htmlkite
- SEBI Combined Risk Disclosure Document: https://www.sebi.gov.in/sebi_data/commondocs/ann4_p.pdf
- SEBI Investor - Securities Market Investment: https://investor.sebi.gov.in/personalsecurities.htmlinvestor.sebi.gov
- SEBI Investor - Video-Based Learning Modules: https://investor.sebi.gov.in/hindi/inv_aware_edu_videos.htmlsebi.gov
