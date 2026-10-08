# Worked example: a book chapter in argument mode

- [The input](#the-input)
- [The output note](#the-output-note)
- [Why these choices matter](#why-these-choices-matter)
- [Illustrative lint and verification](#illustrative-lint-and-verification)

Read when an argument/synthesis note's assembled form is unclear. The chapter
is fictional; [note format](note-format.md), [summary
standards](summary-standards.md) and [non-empirical
reading](edge-cases.md#reading-non-empirical-arguments) own the rules. The
[empirical example](worked-example.md) shows a randomized trial.

## The input

The user asks to "summarize chapter 3 of this book" and names
`Sources/PDFs/Moreau_UrbanCommons_2023/Moreau_UrbanCommons_2023_03_WhyFencesFail.pdf`,
12 physical pages; naming selects a chapter that a folder sweep would skip.
Page 1 gives the title and the byline, Hélène Moreau. The footer prints
`© 2023` with no month or day; no DOI is printed. The scan lists no figures.
By physical page:

- **2:** the familiar claim that an open resource is overused unless it is sold or publicly run.
- **3:** the thesis, *nested commons governance*: user-written rules inside municipal law, which can overrule them.
- **4:** 14 published case studies from nine European cities, chosen by Moreau with no stated search rule; each served at most a few hundred users.
- **6–8:** three features shared by the rules that lasted; rules lasted over five years in 11 of the 14 cases, by the case authors' accounts; each lapsed case lacked a feature.
- **9:** the open question of a city-wide resource, such as a bike-share fleet.
- **10:** advice to city officials to lease rule-making rights for fixed, revocable terms rather than sell or run the resource.
- **11–12:** a table of the cases and their published sources.

## The output note

The destination would be `Articles/Moreau_UrbanCommons_2023_03_WhyFencesFail.md`;
the creation date is illustrative.

```
---
title: "Why fences fail: governing shared urban resources from below"
format: Book
sources:
  - "[[Moreau_UrbanCommons_2023_03_WhyFencesFail.pdf]]"
author:
  - Hélène Moreau
published: 2023-01-01
created: 2026-08-10
description: Moreau argues that city commons last longer under user-written rules than under sale or city control.
tags:
  - "#economics"
read: false
---
> [!Summary]
> - Moreau argues that urban commons last longer when users write and enforce the access rules than when a city sells or runs them. She calls this **nested commons governance**, because the rules sit inside municipal law.
> - Her support is 14 published European case studies that she selected. By the case authors' accounts, rules lasted more than five years in 11 of them.
> - Every case served at most a few hundred users, and the chapter leaves open whether such rules could govern a city-wide resource.

___

## The chapter rejects the choice between selling and centrally running commons

A familiar argument holds that an open resource is overused unless it is sold or run by a public body.<sup>[[Moreau_UrbanCommons_2023_03_WhyFencesFail.pdf#page=2|2]]</sup> Moreau rejects that choice and argues that users can write and enforce the rules themselves.<sup>[[Moreau_UrbanCommons_2023_03_WhyFencesFail.pdf#page=3|3]]</sup>

## A narrative synthesis of 14 European case studies

The chapter synthesizes 14 published case studies of shared resources in nine European cities.<sup>[[Moreau_UrbanCommons_2023_03_WhyFencesFail.pdf#page=4|4]]</sup> Moreau chose the cases and states no search or inclusion rule. She calls user rules nested when municipal law can overrule them.<sup>[[Moreau_UrbanCommons_2023_03_WhyFencesFail.pdf#page=3|3]]</sup>

## Moreau argues three features mark the user rules that lasted

In the rules that lasted, Moreau finds three features:<sup>[[Moreau_UrbanCommons_2023_03_WhyFencesFail.pdf#page=6|6]]</sup>

- **User-written rules.** The users, not the city, wrote the access rules.
- **User monitoring.** The users themselves monitored who used the resource.
- **Graduated sanctions.** Sanctions rose step by step from a warning to exclusion.

By the case authors' accounts, rules were still in force more than five years after adoption in 11 of the 14 cases.<sup>[[Moreau_UrbanCommons_2023_03_WhyFencesFail.pdf#page=7|7]]</sup> She reads each of the three lapsed cases as missing one feature.<sup>[[Moreau_UrbanCommons_2023_03_WhyFencesFail.pdf#page=8|8]]</sup>

## The chapter recommends leasing rule-making rights to user groups

Moreau advises city officials to lease rule-making rights to user groups for fixed, revocable terms instead of selling or running the resource.<sup>[[Moreau_UrbanCommons_2023_03_WhyFencesFail.pdf#page=10|10]]</sup>

## Small, hand-picked cases leave city-wide commons untested

- **Selected, small cases.** Moreau chose the 14 cases without a stated search rule, and each served at most a few hundred users.<sup>[[Moreau_UrbanCommons_2023_03_WhyFencesFail.pdf#page=4|4]]</sup> They show that user-written rules can last, not how often they do. The chapter leaves open whether such rules could govern a city-wide resource such as a bike-share fleet.<sup>[[Moreau_UrbanCommons_2023_03_WhyFencesFail.pdf#page=9|9]]</sup>

## The chapter names every case and its published source

- **Sources.** A closing table lists all 14 cases with the published studies they come from.<sup>[[Moreau_UrbanCommons_2023_03_WhyFencesFail.pdf#page=11|11]]</sup>
```

## Why these choices matter

- **Mode.** The chapter synthesizes other authors' cases and reports no
  procedure of its own, so the second section is prose with no numbered steps.
  The three features are parallel items, so they take bullets under the
  sentence that introduces them; the argument around them stays prose.
- **Attribution.** The opening claim is prior work the chapter restates; the
  thesis and advice are Moreau's and the counts the case authors'. None takes
  an effect rung.
- **One limitation.** Case selection and small scale bound the same reach, so
  one bullet holds both; outside empirical mode it needs no advisory exception.
- **Contrary evidence.** The lapsed cases stay beside the claim they qualify.
- **Frontmatter.** A `format: Book` note has no second `sources:` item. The
  printed `2023` is padded to `2023-01-01`, and the report says so. Had page 1
  printed only the chapter heading, the byline and date would follow the
  [book-chapter rule](note-format.md#frontmatter).
- **Exhibits.** The scan lists no figures, so `--cites` and a page check
  confirm there are none; the claim is the pattern across cases, so the case
  table is not rebuilt.
- **Availability.** `Sources.` is the one relevant label; inapplicable Data
  and Code labels are omitted.

## Illustrative lint and verification

Lint the draft in argument mode, then search the chapter's wording and read
each page:

```bash
python3 '<skill>/scripts/note_lint.py' \
    '<scratch>/Moreau_UrbanCommons_2023_03_WhyFencesFail.md' \
    --mode argument --images '<vault>/Sources/Images' --wiki '<vault>/Wiki'
python3 '<skill>/scripts/paper_text.py' \
    '<vault>/Sources/PDFs/Moreau_UrbanCommons_2023/Moreau_UrbanCommons_2023_03_WhyFencesFail.pdf' \
    --find '11 of the 14' --find 'nine European cities'
```

A found `11 of the 14` still needs page 7 to attribute the count to the case
authors. These are illustrative decisions, not tool results from an included
PDF.
