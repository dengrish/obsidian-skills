# Tag calibration — discipline calls the ownership test does not settle

Scope: discipline calls that the [tag rule](writing.md#tags) and the ownership ("uses") test in [CONVENTIONS §3](../../../shared/CONVENTIONS.md#3-the-discipline-tag-enum) leave undecided, and sources about history, law, politics, finance or business. The machine learning, statistics and mathematics boundary is in the [tag rule](writing.md#tags).

---

## The governing test

**Pick the single discipline where the entity is canonically defined or primarily classified**, not every discipline that uses it. The test for each: in which discipline would this entity appear in a textbook table of contents as a primary topic (not as an applied example)? **The "uses" trap** is that rule in one word: a discipline that *uses* an entity does not own it.

- **Cas9** → `#biology` (a molecular biology system, even though its headline uses are medical).
- **Thermodynamic entropy** → `#physics` (other fields use the concept; physics is the canonical home).
- **Herbert Simon** → one home chosen from the entry's main treatment, such as `#economics` for bounded rationality; other fields remain prose relationships.

When no specific discipline owns the entity, use `#misc` alone. Never leave Wiki tags blank or combine misc with a specific discipline.

## History owns named historical instances

**Named historical instances of laws, treaties, regimes, and political institutions take `#history`, not `#law` or `#political-science`.** History *owns* the entity; law and political-science *use* it as a foundational case (the "uses" trap above) — history owns Magna Carta; constitutional law only cites it.

- **Named historical laws, charters, treaties** → `#history`: `Magna Carta`, `Treaty of Westphalia`, `Code of Hammurabi`.
- **Named historical regimes and institutions** → `#history`: `Holy Roman Empire`, `Soviet Union`, `British East India Company` — institutions whose substance is *what they were* rather than *what they currently are*.
- **General concepts keep their canonical discipline.** *Separation of powers*, *judicial review*, *rule of law* are `#political-science` or `#law`. A specific historic instance exemplifying the concept (`Marbury v. Madison`) is `#history`; the general concept is not.
- **Currently-extant historic institutions** (`British monarchy`, `US Senate`, `United Nations`): `#history` if the body emphasizes historical development and influence, `#political-science` (or `#law`) if it emphasizes contemporary structure and function — choose its dominant treatment when both appear.

## Finance vs economics vs business vs entrepreneurship

**Markets, trading, investing, and asset pricing take `#finance`; company-building takes `#entrepreneurship`; running established companies takes `#business`; economy-wide analysis takes `#economics`.** Finance owns the instruments and the practice of allocating capital; economics *studies* the economy those markets sit in (the "uses" trap again — economics uses market entities it does not own). Entrepreneurship owns founding, early-stage strategy, and venture-building; `#business` keeps management, operations, and strategy of established firms. Venture capital splits on perspective: as an asset class (fund structures, returns) it is `#finance`; the founder-side playbook (raising a round, term sheets from the founder's chair) is `#entrepreneurship`.

- **Finance:** `Options premium selling`, `Modern portfolio theory`, `Capital asset pricing model` — instruments, trading strategies, market structure, asset pricing.
- **Economics:** `Federal Reserve policy`, `Comparative advantage`, `Inflation targeting` — economy-wide mechanisms, incentives, and policy.
- **Entrepreneurship:** `Product-market fit`, `Minimum viable product`, `Blitzscaling` — founding and scaling new companies.
- **Business:** `Porter's five forces`, `Lean manufacturing` — strategy, management and operations of established firms.
- **Cross-disciplinary topic:** `Efficient-market hypothesis` → `#finance`; discuss its economic relationships without adding a second tag.

## When in doubt

Surface the call in the run report's *Notes for the user* with the two-options framing (`Dot product` → math or ML?; `Magna Carta` → history or law?) so the user can override; the cost of getting it wrong is small. Defaults meanwhile: the [tag rule](writing.md#tags) for ML-adjacent entities, `#history` for entities the source primarily treats historically.
