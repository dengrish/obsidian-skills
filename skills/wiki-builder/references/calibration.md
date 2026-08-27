# Tag calibration — the discipline calls the three-way test doesn't settle

> **When to read this:** Read this when either condition holds, and both are checkable before you write a line of the entry: (1) SKILL.md item 8's three-way test (ML / statistics / mathematics) leaves a candidate's `tags:` genuinely undecided; or (2) the source itself is a history, law, political-science, finance/markets, or startup/business document, which you know when you open the file. Otherwise apply the SKILL.md test and skip this file.

---

## The governing test

**Pick the discipline(s) where the entity is canonically defined or primarily classified**, not every discipline that uses it. The test for each: in which discipline would this entity appear in a textbook table of contents as a primary topic (not as an applied example)? **The "uses" trap** is that rule in one word: a discipline that *uses* an entity does not own it.

- **Cas9** → `#biology` (a molecular biology system, even though its headline uses are medical).
- **Thermodynamic entropy** → `#physics` (other fields use the concept; physics is the canonical home).
- **Herbert Simon** → `#economics`, `#psychology`, `#computer-science` (a polymath — multi-tagged rather than left blank).

Blank is legitimate when nothing owns the entity: `Asilomar Conference on Recombinant DNA` → *leave blank*.

## Math vs statistics vs ML

Entities a practitioner encounters in ML courses, papers, or textbooks — losses, metrics, information-theoretic quantities, statistical algorithms, named RL formalisms — take `#machine-learning` even when their origins are mathematical or statistical; the origins belong in the body, not in `tags:`. `#mathematics` is reserved for **universal mathematical concepts** taught across many disciplines as primary topics, where ML is one application among many. **`#statistics` is the home for classical inference and methodology** that is not ML-specific. The same test decides all three — where a practitioner meets the entity as a *primary* topic: a `t`-test or ANOVA is a statistics-course topic, Gini impurity an ML-course topic, a measure-theoretic probability axiom a math-course topic.

- **ML:** `Cross-entropy`, `Mean squared error`, `Markov decision process`.
- **Statistics:** `Hypothesis testing`, `Analysis of variance`, `Pearson correlation coefficient`.
- **Math:** `Random variable`, `Central limit theorem`, `Gaussian distribution`.

Names in these lists are in **canonical title form** (`Mathematical vector`, not `Vector`) — a bare `vector` read off them is the bare-slug failure the disambiguation rules exist to prevent.

**Borderline cases** (`Cosine similarity`, `Dot product`): the deciding test is **whether the entity has a strong independent identity outside ML**. If yes — foundational in another field that uses it independently of ML — prefer `#mathematics`, or `#statistics` where that identity is a classical-statistics one. If no, prefer `#machine-learning`. `Dot product` has independent identity in linear algebra → `#mathematics`; `Cosine similarity` is an inner-product computation whose canonical modern usage is NLP/IR similarity → `#machine-learning`. (`Markov chain` is not borderline — SKILL.md item 8 settles it as `#mathematics`; the exemplars here are ones item 8's lists do not decide.)

## History owns named historical instances

**Named historical instances of laws, treaties, regimes, and political institutions take `#history`, not `#law` or `#political-science`.** History *owns* the entity; law and political-science *use* it as a foundational case (the "uses" trap above) — history owns Magna Carta; constitutional law only cites it.

- **Named historical laws, charters, treaties** → `#history`: `Magna Carta`, `Treaty of Westphalia`, `Code of Hammurabi`.
- **Named historical regimes and institutions** → `#history`: `Holy Roman Empire`, `Soviet Union`, `British East India Company` — institutions whose substance is *what they were* rather than *what they currently are*.
- **General concepts keep their canonical discipline.** *Separation of powers*, *judicial review*, *rule of law* are `#political-science` or `#law`. A specific historic instance exemplifying the concept (`Marbury v. Madison`) is `#history`; the general concept is not.
- **Currently-extant historic institutions** (`British monarchy`, `US Senate`, `United Nations`): `#history` if the body emphasizes historical development and influence, `#political-science` (or `#law`) if it emphasizes contemporary structure and function — **both** when the entry genuinely treats both.

## Finance vs economics vs business vs entrepreneurship

**Markets, trading, investing, and asset pricing take `#finance`; company-building takes `#entrepreneurship`; running established companies takes `#business`; economy-wide analysis takes `#economics`.** Finance owns the instruments and the practice of allocating capital; economics *studies* the economy those markets sit in (the "uses" trap again — economics uses market entities it does not own). Entrepreneurship owns founding, early-stage strategy, and venture-building; `#business` keeps management, operations, and strategy of established firms. Venture capital splits on perspective: as an asset class (fund structures, returns) it is `#finance`; the founder-side playbook (raising a round, term sheets from the founder's chair) is `#entrepreneurship`.

- **Finance:** `Options premium selling`, `Modern portfolio theory`, `Capital asset pricing model` — instruments, trading strategies, market structure, asset pricing.
- **Economics:** `Federal Reserve policy`, `Comparative advantage`, `Inflation targeting` — economy-wide mechanisms, incentives, and policy.
- **Entrepreneurship:** `Product-market fit`, `Minimum viable product`, `Blitzscaling` — founding and scaling new companies.
- **Business:** `Porter's five forces`, `Lean manufacturing` — strategy, management and operations of established firms.
- **Genuinely dual, rarely:** `Efficient-market hypothesis` → `#finance`, `#economics` — a primary topic in both literatures.

## When in doubt

Surface the call in the run report's *Notes for the user* with the two-options framing (`Dot product` → math or ML?; `Magna Carta` → history or law?) so the user can override; the cost of getting it wrong is small. Defaults meanwhile: the independent-identity test for ML-adjacent entities, `#history` for entities the source primarily treats historically.
