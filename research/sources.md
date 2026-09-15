# 出典と読書順

確認日: **2026-09-14**

原著論文、著者公開版、大学の機関リポジトリ、公式仕様・実装を優先した。オンライン資料の現行記述を確認したもので、ソフトウェアのインストール・実行・性能評価は行っていない。研究の対象法令や実装の更新状況を、現在の日本法全体にそのまま一般化しない。

## まず読む5件

1. **片山卓也の国民年金法の形式化** — 日本語の条文と式、Z3Pyの検査を対応付けて読む。
2. **ContractCheck** — 原文から構造化表現を経由し、矛盾や実行可能性を検査する構成を読む。
3. **Catalaの例外チュートリアル** — 原則・例外・優先関係をコードへ写す方法を見る。
4. **BlawxのPrivacy Act実験** — 用語、規則、例外、テストを作る過程を追う。
5. **Programming Z3のModels／Cores** — 具体例と矛盾に関係する制約の取り出し方を読む。

## 日本語・日本法

### S01 — 国民年金法の記述と検証

片山卓也『法令工学の実践 国民年金法の述語論理による記述と検証』。初版2019年、第6版2025年3月。公開書籍・ケーススタディ。

- [大学リポジトリの書誌とファイル](https://dspace.jaist.ac.jp/dspace/handle/10119/16096?mode=full)
- [第6版PDF](https://dspace.jaist.ac.jp/dspace/bitstream/10119/16096/1/fulltext6.pdf)

条文の版と著者が記した限定を確認して読む。

### S02 — 法令工学の背景

島津明、2012年。電子情報通信学会 *Fundamentals Review* 5巻4号、320頁からの法令工学に関する解説。

- [J-STAGE原著ページ](https://www.jstage.jst.go.jp/article/essfr/5/4/5_4_320/_article/-char/ja/)

### S03 — PROLEG

佐藤健ほか、JURISIN 2010。日本の要件事実論に基づくPrologベースの法的推論。

- [著者公開の原著PDF](https://research.nii.ac.jp/~ksatoh/juris-informatics-papers/jurisin2010-ksatoh.pdf)

### S04 — e-Gov法令API／法令XML

公式の法令データ基盤。調査時はVersion 2を参照。

- [API仕様](https://laws.e-gov.go.jp/api/2/swagger-ui)
- [公式データドキュメント](https://laws.e-gov.go.jp/docs/)

### S05 — COLIEE

2026年の公式タスク仕様。検索・含意判定の評価用。

- [Task 3：関連条文と含意判定](https://coliee.org/COLIEE2026/tasks/task3)
- [Task 4：関連条文を与えた含意判定](https://coliee.org/COLIEE2026/tasks/task4)
- [2025年のコーパス形式](https://coliee.org/COLIEE2025/corpus/task3and4)
- [別企画であるNTCIR-11／RITE-VALの説明](https://research.nii.ac.jp/ntcir/ntcir-11/data.html)

## 実装・応用研究

### S06 — ContractCheck

Alan Khoja, Martin Kölbl, Stefan Leue, Rüdiger Wilhelmi. **Automated consistency analysis for legal contracts**. *Artificial Intelligence and Law*, 2025-05-13公開。学術誌論文。

- [原著本文・書誌](https://link.springer.com/article/10.1007/s10506-025-09456-8)

### S07 — Catala

Denis Merigoux, Nicolas Chataing, Jonathan Protzenko. **Catala: A Programming Language for the Law**, 2021。論文と公開コンパイラ。

- [原著](https://arxiv.org/abs/2103.03198)
- [公式リポジトリ](https://github.com/CatalaLang/catala)
- [条件と例外](https://book.catala-lang.org/en/2-2-conditionals-exceptions.html)
- [形式検証の対象・限定](https://github.com/CatalaLang/catala/blob/master/doc/formalization/README.md)

コンパイラは確認時点でApache-2.0。書籍等は別のライセンスを持つ。

### S08 — Blawx／s(CASP)と政府機関の実験

教育・実験向けの公開ツールと、カナダPrivacy Actの形式化事例。

- [Blawx公式リポジトリ](https://github.com/Lexpedite/blawx)
- [カナダ公衆衛生庁DataHubの実験](https://github.com/PHACDataHub/privacy_rac_demo)
- [SWI-Prolog版s(CASP)](https://github.com/SWI-Prolog/sCASP)

確認時点でBlawxはMIT、上記s(CASP)実装はApache-2.0。

### S09 — L4／Legalese

現行公式実装・言語仕様・AI支援のチュートリアル。

- [公式リポジトリ](https://github.com/legalese/l4-ide)
- [例外の意味論](https://legalese.com/l4/concepts/legal-modeling/default-reasoning)
- [AIによるL4案の作成](https://legalese.com/l4/tutorials/llm-integration/composing-l4-with-ai)
- [法文からの取り込み](https://legalese.com/l4/tutorials/llm-integration/legislative-ingestion)
- [CLI機能の説明](https://legalese.com/l4/tutorials/getting-started/l4-cli)

上記repoは確認時点でApache-2.0。ホストされたAIサービスの利用条件とは別。

### S10 — Logical English

法律への適用に関する2021年論文と現行公式実装。制御自然言語による論理プログラミング。

- [著者公開の論文PDF](https://www.doc.ic.ac.uk/~rak/papers/LE%20for%20LA.pdf)
- [公式リポジトリ・更新履歴](https://github.com/LogicalContracts/LogicalEnglish)

上記repoは確認時点でApache-2.0。

### S11 — OpenFisca

税・給付制度の計算と政策シミュレーション。現行公式資料。

- [公式サイト](https://openfisca.org/en/)
- [制度の時点別の変化](https://openfisca.org/doc/coding-the-legislation/40_legislation_evolutions.html)
- [期待値と境界値のテスト](https://openfisca.org/doc/coding-the-legislation/writing_yaml_tests.html)
- [コアのリポジトリ](https://github.com/OpenFisca/openfisca-core)

コアは確認時点でAGPL-3.0。国別パッケージ等は個別に確認する。

### S12 — eFLINT

L. T. van Binsbergenほか、2020年原著。行為、義務、権限などを扱う規範モデリング言語。

- [著者公開の原著PDF](https://ltvanbinsbergen.nl/publications/eflint.pdf)
- [Haskell実装](https://gitlab.com/eflint/haskell-implementation)
- [Goサーバー](https://github.com/Olaf-Erkemeij/eflint-server)

上記Goサーバーは確認時点でGPL-3.0。言語と実装群全体を一括して同じライセンスとしない。

## 理論・形式手法

### S13 — 法律を論理プログラムにする古典

M. J. Sergot, F. Sadri, R. A. Kowalski, F. Kriwaczek, P. Hammond, H. T. Cory. **The British Nationality Act as a Logic Program**. *Communications of the ACM* 29(5), 370–386, 1986。

- [著者公開PDF](https://www.doc.ic.ac.uk/~rak/papers/British%20Nationality%20Act.pdf)

### S14 — Input/Output logic

David Makinson, Leendert van der Torre. **Input/Output Logics**, 2000、および **Constraints for Input/Output Logics**, 2001。*Journal of Philosophical Logic*。

- [2000年論文](https://icr.uni.lu/leonvandertorre/papers/jpl00.pdf)
- [2001年論文](https://icr.uni.lu/leonvandertorre/papers/jpl01.pdf)

### S15 — 許可・例外・優先順位

Guido Governatori, Francesco Olivieri, Antonino Rotolo, Simone Scannapieco. **Computing Strong and Weak Permissions in Defeasible Logic**. *Journal of Philosophical Logic* 42, 799–829, 2013。公開原稿は2012年。

- [著者投稿版と書誌](https://arxiv.org/abs/1212.0079)

### S16 — FormaLex

Daniel Gorín, Sergio Mera, Fernando Schapachnik. **A Software Tool for Legal Drafting**, 2011。

- [論文本文](https://arxiv.org/html/1109.2658)

### S17 — Alloyでの法的要求の分析

Waël Hassan, Luigi Logrippo. **Towards a Process for Legally Compliant Software**. RELAW, 2013。

- [著者公開PDF](https://www.site.uottawa.ca/~luigi/papers/13_RELAW.pdf)

### S18 — 義務論理とIsabelle/HOL

Christoph Benzmüller, Xavier Parent, Leendert van der Torre. **A Deontic Logic Reasoning Infrastructure**. CiE, 2018。

- [著者公開PDF](https://page.mi.fu-berlin.de/cbenzmueller/papers/C69.pdf)
- [大学リポジトリの書誌](https://orbilu.uni.lu/handle/10993/37867?locale=en)

### S19 — I/O logicをSATへ還元するrio

Alexander Steen. **A Reduction of Input/Output Logics to SAT**. 2025年初稿、参照版は2026年改訂のarXiv v2。

- [参照した本文](https://arxiv.org/html/2508.16242v2)
- [公式実装](https://github.com/leoprover/rio)

上記実装はScala、BSD 3-Clause。出版社の雑誌版ではなく、取得できたarXiv版を本文根拠とした。

### S20 — 法的意味の表現と確認

Tomer Libal. **Legal linguistic templates and the tension between legal knowledge representation and reasoning**. *Frontiers in Artificial Intelligence* 6:1136263, 2023。

- [原著本文](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2023.1136263/full)

### S21 — Z3の使用と検査結果

Nikolaj Bjørner, Leonardo de Moura, Lev Nachmanson, Christoph Wintersteiger. **Programming Z3**。公式技術解説。

- [本文](https://z3prover.github.io/papers/programmingz3.html)
- [公式実装](https://github.com/Z3Prover/z3)

## LLMと形式推論

### S22 — Logic-LM

Liangming Panほか。**Logic-LM: Empowering Large Language Models with Symbolic Solvers for Faithful Logical Reasoning**. Findings of EMNLP, 2023。査読会議論文。

- [ACL Anthology原著ページ](https://aclanthology.org/2023.findings-emnlp.248/)
- [実装](https://github.com/teacherpeterpan/Logic-LLM)

### S23 — 米国税法§121のLLM補助形式化

Borchuluun Yadamsuren, Steven Keith Platt, Miguel Diaz. **LLM-Assisted Formalization Enables Deterministic Detection of Statutory Inconsistency in the Internal Revenue Code**, 2025年11月。参照したのはarXiv公開稿。

- [原著・版履歴](https://arxiv.org/abs/2511.11954)
- [Prologと検査例](https://github.com/borchuluun/section121-inconsistency-detection)

### S24 — L4L

Chenほか。**L4L: Towards Trustworthy Legal AI through LLM Agents and Formal Reasoning**。初稿2025年、参照版は2026-03-05のv2。arXiv公開稿。

- [抄録・版履歴](https://arxiv.org/abs/2511.21033)
- [v2本文](https://arxiv.org/html/2511.21033v2)

検索結果の旧称L4Mや、言語L4と混同しない。

### S25 — VERIMED

Bethel Hall, William Eiers. **Neurosymbolic Auditing of Natural-Language Software Requirements**, 2026-05-13。arXiv公開稿。

- [原著・版履歴](https://arxiv.org/abs/2605.13817)
- [v1本文](https://arxiv.org/html/2605.13817v1)

### S26 — 法文の曖昧さを識別する研究

Clement Guitton, Reto Gubelmann, Ghassen Karray, Simon Mayer, Aurelia Tamò-Larrieux. **Identifying open-texture in regulations using LLMs**. *Artificial Intelligence and Law*, 2025-05-06公開。学術誌論文。

- [原著本文](https://link.springer.com/article/10.1007/s10506-025-09450-0)

## 標準と政策上の背景

### S27 — LegalRuleML

**LegalRuleML Core Specification Version 1.0**. OASIS Standard, 2021-08-30。

- [正式仕様](https://docs.oasis-open.org/legalruleml/legalruleml-core-spec/v1.0/os/legalruleml-core-spec-v1.0-os.html)

### S28 — Rules as Code

James Mohun, Alex Roberts. **Cracking the code: Rulemaking for humans and machines**. OECD Working Papers on Public Governance, No. 42, 2020-10-12。

- [OECD原著ページ](https://www.oecd.org/en/publications/2020/10/dechiffrer-le-code_d56cab77.html)

## 次の検索に使える語

- 日本語: 法令工学、法令の論理表現、要件事実、法的推論、規範の整合性検査、制御自然言語。
- 英語: computational law, Rules as Code, statutory formalization, legal contract consistency, deontic logic, defeasible logic, input/output logic, controlled natural language, legal autoformalization, SMT unsat core, counterexample-guided refinement.

この一覧は、原著・公式資料を中心とした初回の読書リスト。文献数は関連する資料をまとめた28項目であり、28本すべてが査読論文という意味ではない。
