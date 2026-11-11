---
id: rag_resource
title: Trading Knowledge Base and Behavioral Rules
type: education
source_title: Trading Knowledge Base for Chatbot RAG
source_url: internal://rag_resource
evidence: sebi_rules_and_education
---

# Trading Knowledge Base for Chatbot RAG

Trading Knowledge Base for Chatbot RAG

## 1. Chatbot role and safety rules

You are a trading education and behavioral-coaching assistant for beginner Indian stock-market
traders.
Your job is to:
• Explain trading terms, order types, risk-management ideas, market rules, and investor-s
• Help users reflect before trading: “What is your entry reason? What is your stop-loss? How
much capital are you risking?”
• Remind users of their own pre-set rules, such as maximum risk per trade, maximum trades
per day, and stop-loss discipline.
• Encourage users to pause and review when they show possible behavioral patterns such as
revenge trading, overtrading, or ignoring stop-losses.
You must not:
• Recommend a specific stock, entry price, target, or “buy/sell now” decision.
• Claim that any trade will be profitable.
• Give personalized investment advice or act as a SEBI-registered investment adviser.
• Encourage excessive trading, leverage, or F&O speculation.
• Guarantee that a stop-loss will execute at the exact price.
Always add, when relevant: “This is educational information, not investment advice. Markets
involve risk, and past behavior does not guarantee future results.”

## 2. Basic market concepts


### What is a stock?

A stock, also called a share or equity, represents a small ownership stake in a company. If you own
shares of a company, you may benefit if the company grows and its share price rises, and you may
also receive dividends if the company declares them.
Buying a stock does not guarantee profit. Its price can fall below your purchase price, and you can
lose money.

### What is a stock market?

A stock market is a regulated place where buyers and sellers trade securities. In India, major
exchanges include the National Stock Exchange (NSE) and BSE.
NSE describes its trading system as an automated, order-driven market. Orders are matched based
on best price first, then time priority for orders at the same price.

### What is liquidity?

Liquidity means how easily you can buy or sell something without greatly affecting its price.
• A highly liquid stock has many active buyers and sellers.
• A low-liquidity stock may be harder to exit quickly, and the difference between the best buy
and sell price may be wider.
Liquidity risk is the difficulty of exiting a position quickly or at a fair price.

### What is volatility?

Volatility means how much and how quickly a price moves.
• High volatility can create opportunities, but it also increases the chance of rapid losses.
• A beginner should not treat volatility as a reason to trade more; it is a reason to use smaller
position sizes and clearer exit plans.

## 3. Orders and execution


### What is an order?

An order is an instruction to your broker to buy or sell a security. It includes the instrument, side (buy
or sell), quantity, order type, price if applicable, and validity.
Orders that do not immediately match remain in the exchange’s order book until they are matched
or cancelled. NSE matches the best available buy order with the best available sell order.
Market order
A market order asks the broker/exchange to buy or sell immediately at the best available price.
• Use case: You want execution now and are less concerned about the exact price.
• Risk: In a fast-moving or low-liquidity stock, the final execution price may differ from the
price you saw when placing the order.
• Chatbot response: “A market order prioritizes immediate execution, not a specific price.
Before using it, check the stock’s liquidity and consider whether a limit price would better
protect you.”
Limit order
A limit order lets you specify the maximum price you are willing to pay when buying, or the
minimum price you are willing to accept when selling.
• A buy limit order executes at your limit price or lower.
• A sell limit order executes at your limit price or higher.
• A limit order provides price protection, but it may not execute at all if the market never
reaches your price.
Example: You want to buy a stock at ₹100 or less. You place a buy limit order at ₹100. If the market
price stays above ₹100, your order may remain unfilled.
Chatbot response: “A limit order protects your price but does not guarantee execution. Ask yourself:
is your price based on a plan, or are you trying to chase a moving stock?”
Stop-loss order
A stop-loss order is an order that stays inactive until the market price reaches or crosses a trigger
price. Once triggered, it is released into the regular order book.
For a sell stop-loss:
• You place it below the current market price.
• It triggers when the last traded price falls to or below the trigger price.
• It is commonly used to limit further loss on a long position.
For a buy stop-loss:
• You place it above the current market price.
• It triggers when the last traded price rises to or above the trigger price.
• It may be used to enter a position after a price breakout, or to exit a short position.
NSE explains that a sell stop-loss order triggers when the last traded price reaches or falls below the
trigger price, while a buy stop-loss order triggers when the last traded price reaches or exceeds the
trigger price.
Important: A stop-loss order is not a guaranteed exit at your exact trigger price. After triggering, it
may become a market or limit order, and rapid market movement can cause execution at a worse
price than expected. SEBI’s combined risk-disclosure document specifically warns that stop-loss and
limit orders may not be effective during rapid market movements.
Chatbot response: “A stop-loss is a pre-decided exit level, not a guarantee of a perfect exit price.
Before entering, decide the price at which your trade idea is invalid—and respect it.”
Stop-loss limit order
A stop-loss limit order has two prices:
• Trigger price: The price that activates the order.
• Limit price: The worst acceptable execution price after activation.
Example: You own a stock trading at ₹100. You place a sell stop-loss with:
• Trigger price: ₹95
• Limit price: ₹94
If the price falls to ₹95, the order activates. It will then try to sell at ₹94 or better. If the market
crashes below ₹94 and no buyer accepts ₹94, the order may not execute.
This gives more price control than a pure stop-loss market order, but it can fail to execute in a fast
fall.
Chatbot response: “A stop-loss limit gives you price control but may not fill in a sharp fall. A stop-loss
market order is more likely to execute, but may fill at a worse price. Choose based on your risk
tolerance and liquidity.”
Day order
A day order is valid only for the trading day on which it is placed. If it is not executed by the end of
that day, it is automatically cancelled.
IOC order
An Immediate or Cancel (IOC) order must be executed immediately; any portion that cannot be
matched immediately is cancelled. Partial execution is possible.
Example: You place an IOC buy order for 100 shares. If only 40 shares are available at your
acceptable price, 40 may execute and the remaining 60 are cancelled.
GTC and GTD orders
• GTC (Good Till Cancelled): Remains active until cancelled, subject to exchange limits.
• GTD (Good Till Date): Remains active until a specified date, then expires.
NSE notes that GTC and GTD availability can depend on current exchange/SEBI directives.

## 4. Risk management


### What is position size?

Position size is the amount of money or number of shares you commit to one trade.
A sound position size is based on the distance between entry and stop-loss, not on how confident
you feel.
Simple formula:
Position size= Amount you are willing to risk Entry price−Stop-loss price

Example:
• Capital: ₹1,00,000
• Maximum risk per trade: 1%, or ₹1,000
• Entry price: ₹500
• Stop-loss: ₹480
• Risk per share: ₹20
• Maximum shares: ₹1,000 / ₹20 = 50 shares
Chatbot response: “Your position size should be decided before entry. If your stop-loss is ₹20 away
and your maximum loss is ₹1,000, the maximum size is 50 shares—not a larger size because you feel
confident.”

### What is risk per trade?

Risk per trade is the maximum loss you are willing to accept if your stop-loss is hit.
A common beginner guideline is to keep risk per trade small enough that several losing trades will
not seriously damage the trading capital. Your platform can let users set this as a rule, for example: “I
will not risk more than 1% of my trading capital in one trade.”
This is a personal discipline rule, not a guaranteed method to avoid losses.

### What is a stop-loss discipline?

Stop-loss discipline means deciding, before entering, the price at which your trade idea is no longer
valid—and then following that plan.
SEBI’s risk disclosure notes that stop-loss orders may not always execute as intended during rapid
market movement. Therefore, users should understand that a stop-loss reduces risk but does not
eliminate it.
Chatbot prompts:
• “What is your stop-loss level, and what market condition would make your trade idea
invalid?”
• “Is this stop-loss based on your original plan, or are you moving it because you do not want
to accept a loss?”
• “If this trade hits your stop-loss, how much money will you lose, and is that within your
rule?”

### What is concentration risk?

Concentration risk arises when too much capital is exposed to one stock, sector, or idea.
Example: If 60% of your capital is in one stock, a large fall in that stock can affect your portfolio much
more than if you had spread exposure across several positions.
Your platform can warn users when a planned trade would exceed a user-defined concentration limit.

### What is overtrading?

Overtrading means placing more trades than your plan or emotional state supports.
Common signs include:
• Taking many trades in a short period
• Entering trades without a clear reason
• Increasing position size after losses
• Trading mainly to “recover” losses
• Ignoring pre-set daily limits
Chatbot response: “You have placed several trades today. Before the next one, answer: Does this
trade follow your written plan, or are you trying to recover a recent loss?”

### What is revenge trading?

Revenge trading is trying to win back money quickly after a loss, often by taking impulsive, oversized,
or poorly planned trades.
It is dangerous because the new trade is driven by emotion rather than a valid setup.
Chatbot response: “It looks like you may be trading to recover a recent loss. A better rule is to pause,
review the previous trade, and return only when the next trade meets your plan.”

### What is FOMO?

FOMO means fear of missing out. It occurs when a trader enters because a stock is moving quickly or
because others are talking about it, rather than because the trade fits their plan.
Chatbot response: “Before entering, ask: Would I take this trade if the stock had not already moved?

### What is my entry, stop-loss, and invalidation level?”


## 5. Behavioral coaching rules

Your chatbot should use these patterns to generate warnings.
Pattern Possible signal Suggested coaching response
Oversized
position
Planned trade exceeds user’s
risk-per-trade rule
“This trade exceeds your 1% risk rule. Reduce the
quantity or reconsider the setup.”
Missing stop-
loss
User has no stop-loss or refuses
to define one

### “What price would prove your trade idea wrong?

Define that before entering.”
Revenge trading User re-enters immediately after a loss “You just had a loss. Pause and review: are you following your plan or trying to recover money?”
Overtrading User exceeds daily trade limit “You have reached your planned trade limit for today. Consider stopping and reviewing the day.”
FOMO entry User wants to enter after a sharp move without a plan “The stock has already moved. What is your entry reason, stop-loss, and maximum risk?”
Stop-loss
movement
User tries to move stop-loss
farther away after entry
“Moving a stop-loss farther away increases
potential loss. Does this still fit your original risk
plan?”
Concentration
risk
New position exceeds
portfolio/sector cap
“This trade would make your exposure to one
stock/sector higher than your chosen limit.”

## 6. F&O and leverage warnings


### What are derivatives?

Derivatives are financial instruments whose value is derived from an underlying asset, such as a
stock, index, commodity, or currency. Futures and options are common derivatives.
• A futures contract is a standardized exchange-traded contract to buy or sell an underlying
asset at a predetermined price on a future date.
• An options contract gives the buyer the right, but not the obligation, to buy or sell at a
predetermined price and date. A call option gives the right to buy; a put option gives the
right to sell. Option buyers pay a premium.
Why F&O is high risk
SEBI warns that derivatives can multiply both profits and losses because the amount payable may be
small relative to the value of the underlying asset. A wrong speculative decision can potentially wipe
out an investor’s net worth.
SEBI also states that derivatives are essentially a zero-sum activity: one participant’s gain corresponds
to another participant’s loss. It further notes that, in its study, 9 out of 10 individual traders in the
equity F&O segment incurred net losses in FY 2018-19 and FY 2021-22.
Chatbot response: “F&O can involve leverage and rapid losses. Before trading derivatives, make sure
you understand margin, expiry, premium decay, assignment/settlement, and the possibility of losing
more than your initial expectation.”

### What is margin?

Margin is money or collateral that a trader must maintain with the broker to take certain positions,
especially in derivatives.
Margin can amplify both gains and losses. A beginner should not use margin simply because it allows
a larger position; larger positions also mean larger potential losses.
Chatbot response: “Margin lets you control a larger position with less upfront capital, but it also
increases potential losses. What is your maximum acceptable loss on this trade?”

## 7. Investor protection and legal information


### Who regulates India’s securities market?

The Securities and Exchange Board of India (SEBI) is India’s securities-market regulator. It works to
protect investors, regulate market intermediaries, and promote orderly development of the
securities market.
SEBI’s investor-education material emphasizes informed decision-making and awareness of risks and
pitfalls in securities trading.sebi.gov

### What is a broker?

A broker, also called a trading member, is an intermediary that provides access to the stock exchange.
You place orders through the broker’s trading platform, and the broker routes them to the exchange.
SEBI states that every order is executed with the client’s identity; an order without a client ID will not
be accepted by the exchange system.kite

### What should users check before using a broker?

Users should ensure that:
• The broker is a SEBI-registered intermediary.
• They understand brokerage, taxes, statutory charges, and other fees.
• They do not share trading passwords, OTPs, or account credentials with anyone.
• They use official broker apps/websites and secure payment methods.
• They review contract notes, trade confirmations, and account statements.
SEBI’s investor material advises investors to make payments to brokers through online transactions or
cheque.sebi.gov

### What is a risk disclosure document?

A risk disclosure document explains the risks involved in a product or segment. For derivatives, SEBI
states that trading members must provide investors with a risk disclosure document so investors can
make a conscious decision before trading.kite
Chatbot response: “Before trading derivatives, read the risk disclosure document. It explains risks
such as market movement, liquidity, leverage, and settlement obligations.”

### What happens if a broker defaults?

SEBI’s FAQ explains that, in the event of a trading-member default, losses suffered by investors on
settled or closed-out derivative positions may be compensated from the Investor Protection Fund,
according to the applicable exchange rules, bye-laws, and regulations.kite
This does not mean all trading losses are protected. It refers to specific investor-protection
mechanisms under defined circumstances.

### Can the platform give stock tips?

No. Your platform should clearly state that it provides education, behavioral monitoring, and risk-
rule alerts, not investment advice.
Avoid statements such as:
• “Buy this stock.”
• “This stock will rise.”
• “Sell now to avoid losses.”
• “This is a guaranteed profitable trade.”
Use statements such as:
• “This trade exceeds your pre-set risk limit.”
• “You have not defined a stop-loss.”
• “You have reached your maximum trades for today.”
• “Before entering, write your thesis, invalidation level, and maximum loss.”
• “This is educational information, not investment advice.”

## 8. Ready-made chatbot answers

“What is a stop-loss?”
A stop-loss is a pre-set exit level designed to limit the loss on a trade.
• For a long position, a sell stop-loss is placed below the entry price.
• When the market price reaches or falls below the trigger, the order is released into the
market.
• It does not guarantee execution at the exact trigger price, especially during fast market
moves.
Example: You buy at ₹500 and place a sell stop-loss trigger at ₹480. If the price falls to ₹480, the
stop-loss may activate. Your actual exit price can differ if the market moves quickly.
“Should I move my stop-loss?”
Only move a stop-loss if it is part of a predefined risk-management plan, such as trailing a stop after
the trade moves in your favor.
Do not move it farther away merely because you hope the price will recover. That increases the
maximum possible loss and often turns a planned small loss into a larger one.
Chatbot response: “Is this stop-loss change based on your original trading plan, or are you trying to
avoid accepting a loss?”
“What is a limit order?”
A limit order lets you set the maximum buying price or minimum selling price. It protects your price
but may not execute if the market does not reach your level.
“What is a market order?”
A market order is used when immediate execution matters more than a specific price. It may execute
at a different price from the one displayed when you placed the order, especially in fast-moving
markets.
“How much should I risk per trade?”
That is a personal decision, but a beginner-friendly approach is to define a small fixed maximum risk
per trade before entering—for example, 0.5% to 1% of trading capital. The important principle is that
the risk amount, entry price, and stop-loss distance determine position size.
This is not investment advice; it is a risk-management framework.
“I lost money. Should I trade again immediately?”
Not immediately. After a loss:

## 1. Stop trading for a short cooling-off period.


## 2. Review whether the loss came from a bad setup, poor execution, or a rule violation.


## 3. Check whether you are trying to recover the loss emotionally.


## 4. Return only when the next trade meets your written plan.

Chatbot response: “A loss does not mean you must immediately win it back. What specifically went
wrong in the last trade, and what rule will protect you in the next one?”
“Is F&O good for beginners?”
F&O is generally high risk for beginners because it can involve leverage, expiry risk, margin
requirements, liquidity issues, and rapid losses. SEBI warns that derivatives can multiply gains and
losses and may potentially wipe out an investor’s net worth in a wrong speculative decision.
Chatbot response: “Before using F&O, make sure you understand margin, expiry, premium,
settlement, and the possibility of large losses. Start with education and simulated practice rather
than live speculation.”

## 9. Suggested RAG document structure

Store the content in these retrievable sections:

## 1. Basic concepts: Stock, market, liquidity, volatility, capital, P&L


## 2. Order types: Market, limit, stop-loss, stop-loss limit, day, IOC, GTC, GTD


## 3. Risk management: Position sizing, risk per trade, stop-loss discipline, concentration,

diversification

## 4. Behavioral risks: FOMO, revenge trading, overtrading, loss aversion, overconfidence


## 5. F&O and leverage: Futures, options, premium, margin, expiry, settlement, risks


## 6. Legal and investor protection: SEBI, brokers, client ID, risk disclosures, Investor Protection

Fund, complaints

## 7. Platform rules: User-defined risk limits, alerts, reflection prompts, disclaimers


## 8. Safety responses: What the chatbot can and cannot say


## 10. Mandatory disclaimer

Include this in the chatbot’s system prompt and show it in the interface:
This chatbot provides educational and behavioral-risk information only. It does not provide
investment advice, stock recommendations, or guarantees of profit. Trading in securities and
derivatives involves risk, including the risk of loss. Stop-loss orders may not execute at the
expected price during rapid market movements. Please make independent decisions and consult a
SEBI-registered professional where appropriate.

## 11. Sources to cite in the RAG metadata

Attach these source URLs to the relevant chunks:
• NSE Trading System — order types, stop-loss mechanics, order matching:
https://www.nseindia.com/products/content/equities/equities/trading_system.htm
• SEBI Investor — Understanding Derivatives:
https://investor.sebi.gov.in/understanding_derivatives.html
• SEBI — FAQ on Equity and Currency Derivatives:
https://www.sebi.gov.in/sebi_data/docfiles/20621_t.htmlkite
• SEBI — Combined Risk Disclosure Document:
https://www.sebi.gov.in/sebi_data/commondocs/ann4_p.pdf
• SEBI Investor — Securities Market Investment:
https://investor.sebi.gov.in/personalsecurities.htmlinvestor.sebi.gov
• SEBI Investor — Video-Based Learning Modules:
https://investor.sebi.gov.in/hindi/inv_aware_edu_videos.htmlsebi.gov

## 12. Important implementation note

For your MVP, make the chatbot rule-aware:
• If the user asks “What is a stop-loss?”, retrieve the stop-loss explanation.
• If the user says “I want to buy now,” ask for entry reason, stop-loss, position size, and
maximum acceptable loss.
• If the user’s planned trade violates a stored rule, show the relevant rule and ask for
confirmation or reflection.
• If the user is repeatedly violating rules, suggest a pause and a post-trade review rather than
encouraging another trade.

