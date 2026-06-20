# Golden Evaluation Dataset — Indian Legal RAG (CPC corpus)

**54 questions** hand-curated from `LEGAL_DATA/` and traced to source `doc_id`s. 
Machine-readable source of truth: `golden_dataset.jsonl`. Validate with `python validate_golden.py`.

## Coverage

| Question type | Count |
|---|---|
| Single-hop · case metadata | 7 |
| Single-hop · statute lookup | 8 |
| Single-hop · holding / ratio | 6 |
| Multi-hop (2) · judgment → provision | 8 |
| Multi-hop (2) · provision → cases | 5 |
| Multi-hop (3) · bridge across cases | 4 |
| Comparison · cross-document | 5 |
| Doctrine / conceptual | 3 |
| Case → case citation | 2 |
| Temporal / amendment | 2 |
| Negative · must abstain | 4 |
| **Total** | **54** |

Difficulty: **easy** 14, **medium** 26, **hard** 14

## How to cross-verify an answer

Open `LEGAL_DATA/judgments/<doc_id>.json` or `LEGAL_DATA/provisions/<doc_id>.json`, search its `body` for the quoted **Source span**, and confirm the answer. For multi-hop rows, the `verification_note` names the exact citation edge (e.g. `judgment.cited_provisions` or `provision.cases_citedby`) that links the documents.

## Single-hop · case metadata

### Q001 · easy · 1 hop(s)

**Q:** In which court and on what date was the petition in 'Sh. Sunder Lal Gupta vs M/S Sahyog Hospitality' decided?

**Gold answer:** The Delhi High Court (Justice Harish Vaidyanathan Shankar) decided it on 27 April 2026.

**Source span:** "IN THE HIGH COURT OF DELHI AT NEW DELHI Date of decision: 27.04.2026"

**Source doc_ids:** 100420250  ·  **expected:** `answer`

_Verify:_ Court name and decision date in judgment header.

### Q002 · easy · 1 hop(s)

**Q:** Which court decided 'Narayanan Rajendran vs Lekshmy Sarojini' and who authored the judgment?

**Gold answer:** The Supreme Court of India; the judgment was authored by Justice Dalveer Bhandari (Bench: Harjit Singh Bedi, Dalveer Bhandari).

**Source span:** "IN THE SUPREME COURT OF INDIA"

**Source doc_ids:** 1077888  ·  **expected:** `answer`

_Verify:_ Header states Supreme Court; Author: Dalveer Bhandari, J.

### Q003 · easy · 1 hop(s)

**Q:** Under what petition number and in which High Court was 'Elis Jane Quinlan vs Naveen Kumar Seth' filed?

**Gold answer:** Writ Petition No. 14283 of 2023 in the High Court of Judicature at Bombay (Justice Sandeep V. Marne), decided 10 February 2026.

**Source span:** "IN THE HIGH COURT OF JUDICATURE AT BOMBAY CIVIL APPELLATE JURISDICTION WRIT PETITION NO. 14283 OF 2023"

**Source doc_ids:** 156512963  ·  **expected:** `answer`

_Verify:_ Bombay HC header with WP number.

### Q004 · easy · 1 hop(s)

**Q:** Which High Court bench decided 'Perumal vs Marudaiyappan' and in what year?

**Gold answer:** The Madurai Bench of the Madras High Court (Justice S. Ramathilagam), on 20 March 2019.

**Source span:** "BEFORE THE MADURAI BENCH OF MADRAS HIGH COURT DATED: 20.03.2019"

**Source doc_ids:** 144018669  ·  **expected:** `answer`

_Verify:_ Madras HC Madurai bench header.

### Q005 · easy · 1 hop(s)

**Q:** Which High Court decided 'M.P. Krishi Upaj Mandi Samiti vs Prakash Nagpal' and what was the outcome of the petition?

**Gold answer:** The Madhya Pradesh High Court at Jabalpur (Justice Gurpal Singh Ahluwalia); the petition was allowed.

**Source span:** "IN THE HIGH COURT OF MADHYA PRADESH AT JABALPUR"

**Source doc_ids:** 175747345  ·  **expected:** `answer`

_Verify:_ MP HC Jabalpur header; outcome 'the petition is allowed.'

### Q006 · easy · 1 hop(s)

**Q:** In which High Court was the second appeal in 'Dibakar Naik vs Sri Nuduru @ Prafulla Mohanta' heard, and what was decided?

**Gold answer:** The Orissa High Court at Cuttack (Justice Ananda Chandra Behera); both second appeals were allowed on merit.

**Source span:** "ORISSA HIGH COURT : CUTTACK"

**Source doc_ids:** 13925394  ·  **expected:** `answer`

_Verify:_ Orissa HC header; outcome 'both the 2nd Appeals ... are allowed on merit.'

### Q007 · easy · 1 hop(s)

**Q:** Which court decided the first appeal in 'Oil And Natural Gas Corporation Limited vs Hindustan Chemicals Company'?

**Gold answer:** The High Court of Gujarat at Ahmedabad (Justices A. S. Supehia and Divyesh A. Joshi); the first appeal was allowed.

**Source span:** "IN THE HIGH COURT OF GUJARAT AT AHMEDABAD"

**Source doc_ids:** 105140378  ·  **expected:** `answer`

_Verify:_ Gujarat HC header.

## Single-hop · statute lookup

### Q008 · easy · 1 hop(s)

**Q:** What does Section 9 of the Code of Civil Procedure, 1908 provide about the jurisdiction of civil courts?

**Gold answer:** Section 9 says civil courts have jurisdiction to try all suits of a civil nature except those whose cognizance is expressly or impliedly barred.

**Source span:** "have jurisdiction to try all suits of a civil nature excepting suits of which their cognizance is either expressly or impliedly barred"

**Source doc_ids:** 76869205  ·  **expected:** `answer`

_Verify:_ Verbatim from Section 9 body.

### Q009 · easy · 1 hop(s)

**Q:** What power does Section 34 of the CPC give a court regarding interest on a money decree?

**Gold answer:** Where a decree is for payment of money, the court may order interest at a rate it deems reasonable on the principal sum adjudged, from the date of suit to the date of the decree.

**Source span:** "order interest at such rate as the Court deems reasonable to be paid on the principal sum adjudged, from the date of the suit to the date of the decree"

**Source doc_ids:** 107990682  ·  **expected:** `answer`

_Verify:_ Verbatim from Section 34(1).

### Q010 · medium · 1 hop(s)

**Q:** Under Section 47 CPC, who decides questions relating to the execution, discharge or satisfaction of a decree?

**Gold answer:** The court executing the decree decides such questions, not a separate suit.

**Source span:** "relating to the execution, discharge or satisfaction of the decree, shall be determined by the Court executing the decree and not by a separate suit"

**Source doc_ids:** 119552888  ·  **expected:** `answer`

_Verify:_ Verbatim from Section 47(1).

### Q011 · medium · 1 hop(s)

**Q:** What does Section 100A CPC say about a further appeal from a decision of a Single Judge of a High Court?

**Gold answer:** Where an appeal from an original or appellate decree/order is heard and decided by a Single Judge of a High Court, no further appeal lies from that judgment and decree.

**Source span:** "is heard and decided by a Single Judge of a High Court, no further appeal shall lie from the judgment and decree of such Single Judge"

**Source doc_ids:** 144428047  ·  **expected:** `answer`

_Verify:_ Verbatim from Section 100A.

### Q012 · easy · 1 hop(s)

**Q:** What kind of mistakes may be corrected under Section 152 of the CPC?

**Gold answer:** Clerical or arithmetical mistakes in judgments, decrees or orders, or errors from any accidental slip or omission, may be corrected at any time by the court on its own motion or on a party's application.

**Source span:** "Clerical or arithmetical mistakes in judgments, decrees or orders or errors arising therein from any accidental slip or omission may at any time be corrected by the Court"

**Source doc_ids:** 150586894  ·  **expected:** `answer`

_Verify:_ Verbatim from Section 152.

### Q013 · easy · 1 hop(s)

**Q:** In which court must a suit be instituted under Section 15 of the CPC?

**Gold answer:** In the court of the lowest grade competent to try it.

**Source span:** "Every suit shall be instituted in the Court of the lowest grade competent to try it"

**Source doc_ids:** 167618813  ·  **expected:** `answer`

_Verify:_ Verbatim from Section 15.

### Q014 · easy · 1 hop(s)

**Q:** What does Section 6 of the CPC say about pecuniary jurisdiction?

**Gold answer:** Except as expressly provided, nothing in the Code gives a court jurisdiction over suits whose subject-matter value exceeds the pecuniary limits of its ordinary jurisdiction.

**Source span:** "nothing herein contained shall operate to give any Court jurisdiction over suits the amount or value of the subject-matter of which exceeds the pecuniary limits"

**Source doc_ids:** 31796670  ·  **expected:** `answer`

_Verify:_ Verbatim from Section 6.

### Q015 · medium · 1 hop(s)

**Q:** How does Section 2 of the CPC define a 'decree'?

**Gold answer:** A 'decree' is the formal expression of an adjudication which conclusively determines the rights of the parties on the matters in controversy in the suit, and may be preliminary or final.

**Source span:** ""decree" means the formal expression of an adjudication which, so far as regards the Court expressing it, conclusively determines the rights of the parties"

**Source doc_ids:** 78563457  ·  **expected:** `answer`

_Verify:_ Verbatim from Section 2(2).

## Single-hop · holding / ratio

### Q016 · medium · 1 hop(s)

**Q:** In the Sunder Lal Gupta arbitration-enforcement matter, what did the Delhi High Court ultimately decide about the petition under Section 17(2)?

**Gold answer:** Because the Final Award had been rendered during the petition and had subsumed the interim order, the court held the Section 17(2) reliefs could not be granted and dismissed the petition.

**Source span:** "Accordingly, the present Petition stands dismissed"

**Source doc_ids:** 100420250  ·  **expected:** `answer`

_Verify:_ Operative holding in para 33.

### Q017 · medium · 1 hop(s)

**Q:** What did the Kerala High Court hold in 'John George vs Stewards Association in India' about an appeal to a Division Bench under Section 100A?

**Gold answer:** It held that Section 100-A CPC bars an appeal to a Division Bench against a Single Judge's appellate-jurisdiction judgment, and such appeals filed after 1.7.2002 are not maintainable.

**Source span:** "Section 100-A of Code of Civil Procedure bars an appeal to a Division Bench"

**Source doc_ids:** 1528427  ·  **expected:** `answer`

_Verify:_ Holding in para 12.

### Q018 · medium · 1 hop(s)

**Q:** What was the Supreme Court's central holding in 'Narayanan Rajendran' about a High Court's powers in a second appeal under Section 100?

**Gold answer:** The High Court should not interfere with concurrent findings of fact in a second appeal without formulating a substantial question of law; doing so here was unsustainable, so the SC set aside the HC judgment.

**Source span:** "refrain from interfering with the concurrent findings of fact without formulating substantial question of law"

**Source doc_ids:** 1077888  ·  **expected:** `answer`

_Verify:_ Holding near para 72-73.

### Q019 · medium · 1 hop(s)

**Q:** In 'Latha Menon vs Ponnamma', what did the Kerala High Court decide about the earlier decision in Seetha Ramachandran?

**Gold answer:** It overruled Seetha Ramachandran to the extent it held that sub-rules (1)-(3) of Order XXIII Rule 1 do not apply to interlocutory applications.

**Source span:** "The decision in Seetha Ramachandran is overruled to that extent"

**Source doc_ids:** 166436152  ·  **expected:** `answer`

_Verify:_ Operative overruling line.

### Q020 · medium · 1 hop(s)

**Q:** In 'Auto Trade And Finance Corporation vs Raj Kishore Sanganaria', why was the execution application dismissed?

**Gold answer:** Because the decree-holder approached the wrong forum to execute the decree beyond its territorial limits; such an application must be rejected, so the execution application was dismissed.

**Source span:** "he approaches the wrong forum at his own peril"

**Source doc_ids:** 181760  ·  **expected:** `answer`

_Verify:_ Reasoning in final paras.

### Q021 · medium · 1 hop(s)

**Q:** In 'M.P. Krishi Upaj Mandi Samiti vs Prakash Nagpal', what did the court hold about the application filed under Section 94 CPC?

**Gold answer:** The court held the application under Section 94 CPC was not maintainable and set aside the impugned order, giving liberty to file under Order 39 Rule 1 and 2.

**Source span:** "the application filed under Section 94 of CPC was not maintainable"

**Source doc_ids:** 175747345  ·  **expected:** `answer`

_Verify:_ Holding in para 18.

## Multi-hop (2) · judgment → provision

### Q022 · medium · 2 hop(s)

**Q:** The second appeal in 'Narayanan Rajendran' was filed under which CPC provision, and what threshold does that provision require?

**Gold answer:** Section 100 CPC. It allows a second appeal to the High Court only if the case involves a substantial question of law.

**Source span:** "if the High Court is satisfied that the case involves a substantial question of law"

**Source doc_ids:** 1077888, 192138551  ·  **expected:** `answer`

_Verify:_ 1077888.cited_provisions contains 192138551 (Section 100); span from Section 100 body.

### Q023 · medium · 2 hop(s)

**Q:** John George's case turned on a CPC provision barring a further appeal from a Single Judge — which provision, and what does it state?

**Gold answer:** Section 100A CPC, which bars any further appeal where an appeal is heard and decided by a Single Judge of a High Court.

**Source span:** "no further appeal shall lie from the judgment and decree of such Single Judge"

**Source doc_ids:** 1528427, 144428047  ·  **expected:** `answer`

_Verify:_ 1528427.cited_provisions contains 144428047 (Section 100A); span from Section 100A body.

### Q024 · medium · 2 hop(s)

**Q:** The execution dispute in 'Elis Jane Quinlan' concerned a foreign decree — which CPC provision governs execution of decrees from reciprocating territories?

**Gold answer:** Section 44A CPC, on execution of decrees passed by courts in a reciprocating territory.

**Source span:** "Execution of decrees passed by Courts in reciprocating territory"

**Source doc_ids:** 156512963, 51234069  ·  **expected:** `answer`

_Verify:_ 156512963.cited_provisions contains 51234069 (Section 44A); span from Section 44A title/body.

### Q025 · medium · 2 hop(s)

**Q:** The ONGC interest dispute was decided under which CPC provision on interest, and what does it empower the court to do?

**Gold answer:** Section 34 CPC, which empowers the court to order reasonable interest on the principal sum of a money decree from the date of suit to the date of the decree.

**Source span:** "the Court may, in the decree, order interest at such rate as the Court deems reasonable"

**Source doc_ids:** 105140378, 107990682  ·  **expected:** `answer`

_Verify:_ 105140378.cited_provisions contains 107990682 (Section 34); span from Section 34 body.

### Q026 · medium · 2 hop(s)

**Q:** In the M.P. Krishi Upaj Mandi case the court found an application under a particular CPC section non-maintainable — what is that section about?

**Gold answer:** Section 94 CPC (supplemental proceedings), which lets the court take certain steps to prevent the ends of justice being defeated.

**Source span:** "In order to prevent the ends of justice from being defeated the Court may, if it is so prescribed"

**Source doc_ids:** 175747345, 196220096  ·  **expected:** `answer`

_Verify:_ 175747345.cited_provisions contains 196220096 (Section 94); span from Section 94 body.

### Q027 · hard · 2 hop(s)

**Q:** The execution in 'Auto Trade And Finance Corporation' raised the question of sending a decree to another court — which CPC provision governs transfer of a decree for execution?

**Gold answer:** Section 39 CPC, under which the court that passed a decree may, on the decree-holder's application, send it for execution to another court of competent jurisdiction.

**Source span:** "may, on the application of the decree-holder, send it for execution to another Court"

**Source doc_ids:** 181760, 39530104  ·  **expected:** `answer`

_Verify:_ 181760.cited_provisions contains 39530104 (Section 39); span from Section 39 body.

### Q028 · hard · 2 hop(s)

**Q:** In 'Latha Menon', which CPC section was used to decide whether Order XXIII Rule 1 applies to interlocutory applications, and what does that section provide?

**Gold answer:** Section 141 CPC, which makes the procedure for suits applicable, as far as it can be, to all proceedings in any court of civil jurisdiction.

**Source span:** "The procedure provided in this Code in regard to suits shall be followed, as far as it can be made applicable, in all proceedings in any Court of civil jurisdiction"

**Source doc_ids:** 166436152, 133762466  ·  **expected:** `answer`

_Verify:_ 166436152.cited_provisions contains 133762466 (Section 141); span from Section 141 body.

### Q029 · medium · 2 hop(s)

**Q:** The Orissa second appeals in 'Dibakar Naik' were filed under which CPC provision, and what does it require for the High Court to interfere?

**Gold answer:** Section 100 CPC; a second appeal lies to the High Court only if the case involves a substantial question of law.

**Source span:** "an appeal shall lie to the High Court from every decree passed in appeal by any Court subordinate to the High Court"

**Source doc_ids:** 13925394, 192138551  ·  **expected:** `answer`

_Verify:_ 13925394.cited_provisions contains 192138551 (Section 100); span from Section 100 body.

## Multi-hop (2) · provision → cases

### Q030 · hard · 2 hop(s)

**Q:** Which judgments in this corpus are linked to Section 100 CPC (second appeal)? Name at least two.

**Gold answer:** Section 100 CPC governs second appeals; corpus cases linked to it include 'Narayanan Rajendran vs Lekshmy Sarojini' (1077888) and 'Gurdev Kaur vs Kaki' (1754551).

**Source span:** "Second appeal"

**Source doc_ids:** 192138551, 1077888, 1754551  ·  **expected:** `answer`

_Verify:_ 1077888 and 1754551 appear in 192138551.cases_citedby; span from Section 100 title.

### Q031 · hard · 2 hop(s)

**Q:** Which corpus cases are linked to Section 44A CPC (execution of foreign decrees)? Give two.

**Gold answer:** 'Elis Jane Quinlan vs Naveen Kumar Seth' (156512963) and 'Radhamani India Ltd. vs Imperial Garments Ltd.' (1022750).

**Source span:** "Execution of decrees passed by Courts in reciprocating territory"

**Source doc_ids:** 51234069, 156512963, 1022750  ·  **expected:** `answer`

_Verify:_ 156512963 and 1022750 appear in 51234069.cases_citedby.

### Q032 · hard · 2 hop(s)

**Q:** Which corpus cases relate to Section 89 CPC (settlement of disputes outside court)? Name two.

**Gold answer:** 'Bindu Balakrishna Patali vs Smartowner Services' (14958608) and 'Mrs. Sunandamma P vs M/S GTL Infrastructure' (62240867).

**Source span:** "Settlement of disputes outside the Court"

**Source doc_ids:** 66488754, 14958608, 62240867  ·  **expected:** `answer`

_Verify:_ 14958608 and 62240867 appear in 66488754.cases_citedby.

### Q033 · hard · 2 hop(s)

**Q:** Which corpus cases are connected to Section 16 CPC (suits to be instituted where subject-matter is situate)? Give two.

**Gold answer:** 'Polotrips India Pvt. Ltd. vs Karnataka Bank Limited' (47339847) and 'GSL (India) Ltd vs Asset Reconstruction Co.' (183942004).

**Source span:** "Suits to be instituted where subject-matter situate"

**Source doc_ids:** 169730061, 47339847, 183942004  ·  **expected:** `answer`

_Verify:_ 47339847 and 183942004 appear in 169730061.cases_citedby (Section 16, place of suing).

### Q034 · hard · 2 hop(s)

**Q:** Name two corpus cases linked to Section 152 CPC (amendment of judgments/decrees for clerical errors).

**Gold answer:** 'Rakesh Kumar And Others vs Ashok Kumar' (188852815) is among the corpus cases linked to Section 152.

**Source span:** "Amendment of judgments, decrees or orders"

**Source doc_ids:** 150586894, 188852815  ·  **expected:** `answer`

_Verify:_ 188852815 appears in 150586894.cases_citedby.

## Multi-hop (3) · bridge across cases

### Q035 · hard · 3 hop(s)

**Q:** Besides 'Narayanan Rajendran', which other corpus judgment also turns on Section 100 CPC, and what do they share?

**Gold answer:** 'Dibakar Naik vs Sri Nuduru' (13925394) also turns on Section 100 CPC; both are second appeals where the scope of High Court interference depends on a substantial question of law.

**Source span:** "if the High Court is satisfied that the case involves a substantial question of law"

**Source doc_ids:** 1077888, 192138551, 13925394  ·  **expected:** `answer`

_Verify:_ Both 1077888 and 13925394 list 192138551 (Section 100) in cited_provisions.

### Q036 · hard · 3 hop(s)

**Q:** Which other corpus case besides 'John George' relies on Section 100A CPC, and on what common point?

**Gold answer:** 'Asha D/O Bhalchandra Joshi vs National Insurance Co.' (1737105) also relies on Section 100A CPC; both address the maintainability of a further/Letters Patent appeal from a Single Judge.

**Source span:** "no further appeal shall lie from the judgment and decree of such Single Judge"

**Source doc_ids:** 1528427, 144428047, 1737105  ·  **expected:** `answer`

_Verify:_ Both 1528427 and 1737105 list 144428047 (Section 100A) in cited_provisions.

### Q037 · hard · 3 hop(s)

**Q:** Starting from 'M.P. Krishi Upaj Mandi Samiti', which other corpus case also invokes Section 9 CPC on civil court jurisdiction?

**Gold answer:** 'Latha Menon vs Ponnamma' (166436152) also invokes Section 9 CPC; both engage the principle that civil courts try all civil suits unless cognizance is expressly or impliedly barred.

**Source span:** "excepting suits of which their cognizance is either expressly or impliedly barred"

**Source doc_ids:** 175747345, 76869205, 166436152  ·  **expected:** `answer`

_Verify:_ Both 175747345 and 166436152 list 76869205 (Section 9) in cited_provisions.

### Q038 · hard · 3 hop(s)

**Q:** 'Asha Joshi' and which other corpus case both rely on Section 11 CPC (res judicata)?

**Gold answer:** 'Latha Menon vs Ponnamma' (166436152) also relies on Section 11 CPC; both engage the bar on re-trying a matter already finally decided between the same parties.

**Source span:** "No Court shall try any suit or issue in which the matter directly and substantially in issue has been directly and substantially in issue in a former suit"

**Source doc_ids:** 1737105, 121631892, 166436152  ·  **expected:** `answer`

_Verify:_ Both 1737105 and 166436152 list 121631892 (Section 11) in cited_provisions.

## Comparison · cross-document

### Q039 · medium · 2 hop(s)

**Q:** How does a first appeal under Section 96 CPC differ from a second appeal under Section 100 CPC?

**Gold answer:** A first appeal (Section 96) lies from a decree of a court of original jurisdiction and can be on fact and law; a second appeal (Section 100) lies to the High Court only where the case involves a substantial question of law.

**Source span:** "an appeal shall lie from every decree passed by any Court exercising original jurisdiction"

**Source doc_ids:** 72075529, 192138551  ·  **expected:** `answer`

_Verify:_ Span from Section 96; contrast drawn with Section 100's substantial-question-of-law requirement.

### Q040 · hard · 2 hop(s)

**Q:** What is the difference between Section 10 CPC (stay of suit) and Section 11 CPC (res judicata)?

**Gold answer:** Section 10 stays the trial of a later suit while an earlier suit on the same matter between the same parties is pending; Section 11 bars trying a suit/issue already heard and finally decided in a former suit. One concerns a pending suit, the other a decided one.

**Source span:** "No Court shall proceed with the trial of any suit in which the matter in issue is also directly and substantially in issue in a previously instituted suit"

**Source doc_ids:** 85279687, 121631892  ·  **expected:** `answer`

_Verify:_ Span from Section 10; contrast drawn with Section 11 (res judicata).

### Q041 · medium · 2 hop(s)

**Q:** When does a second appeal lie under Section 100 CPC, and in what money-suit situation is it barred by Section 102 CPC?

**Gold answer:** Section 100 allows a second appeal where a substantial question of law is involved; Section 102 bars any second appeal where the original suit was for recovery of money not exceeding twenty-five thousand rupees.

**Source span:** "No second appeal shall lie from any decree, when the subject matter of the original suit is for recovery of money not exceeding twenty-five thousand rupees"

**Source doc_ids:** 192138551, 114551302  ·  **expected:** `answer`

_Verify:_ Span from Section 102; contrast with Section 100.

### Q042 · hard · 2 hop(s)

**Q:** Contrast Section 14 CPC and Section 44A CPC in how they treat foreign judgments and decrees.

**Gold answer:** Section 14 raises a presumption that a certified copy of a foreign judgment was pronounced by a competent court (rebuttable by proving want of jurisdiction); Section 44A allows actual execution in India of a decree of a superior court of a reciprocating territory once its certified copy is filed in a District Court.

**Source span:** "The Court shall presume, upon the production of any document purporting to be a certified copy of, a foreign judgment"

**Source doc_ids:** 32382254, 51234069  ·  **expected:** `answer`

_Verify:_ Span from Section 14; contrast with Section 44A execution.

### Q043 · hard · 2 hop(s)

**Q:** Compare the outcomes in 'Narayanan Rajendran' and 'Dibakar Naik' regarding High Court interference in second appeals.

**Gold answer:** In Narayanan Rajendran the Supreme Court faulted the High Court for reversing concurrent findings without a substantial question of law and restored the lower courts' findings; in Dibakar Naik the Orissa High Court itself allowed the second appeals on merit and set aside the lower decrees. Both hinge on the Section 100 substantial-question-of-law gateway.

**Source span:** "are allowed on merit"

**Source doc_ids:** 1077888, 13925394  ·  **expected:** `answer`

_Verify:_ Span from Dibakar Naik outcome; contrast with Narayanan Rajendran holding.

## Doctrine / conceptual

### Q044 · easy · 1 hop(s)

**Q:** Explain the doctrine of res judicata as codified in the CPC.

**Gold answer:** Res judicata (Section 11 CPC) bars a court from trying any suit or issue that was directly and substantially in issue in a former suit between the same parties (or those claiming under them) and was heard and finally decided by a competent court.

**Source span:** "No Court shall try any suit or issue in which the matter directly and substantially in issue has been directly and substantially in issue in a former suit between the same parties"

**Source doc_ids:** 121631892  ·  **expected:** `answer`

_Verify:_ Section 11 text.

### Q045 · easy · 1 hop(s)

**Q:** What is the doctrine of res sub judice (stay of suit) under the CPC?

**Gold answer:** Under Section 10 CPC, a court must not proceed with the trial of a suit whose matter in issue is also directly and substantially in issue in a previously instituted, still-pending suit between the same parties litigating under the same title.

**Source span:** "No Court shall proceed with the trial of any suit in which the matter in issue is also directly and substantially in issue in a previously instituted suit"

**Source doc_ids:** 85279687  ·  **expected:** `answer`

_Verify:_ Section 10 (stay of suit) text.

### Q046 · medium · 1 hop(s)

**Q:** What modes of out-of-court dispute settlement can a court refer parties to under Section 89 CPC?

**Gold answer:** Where elements of a settlement exist, the court may formulate terms and refer the dispute to arbitration, conciliation, judicial settlement (including Lok Adalat), or mediation.

**Source span:** "(a) arbitration; (b) conciliation; (c) judicial settlement including settlement through Lok Adalat; or (d) mediation"

**Source doc_ids:** 66488754  ·  **expected:** `answer`

_Verify:_ Section 89(1) modes.

## Case → case citation

### Q049 · medium · 2 hop(s)

**Q:** Which Constitution Bench Supreme Court decision does 'John George vs Stewards Association' discuss on the Letters Patent / Section 100A question?

**Gold answer:** It discusses 'P.S. Sathappan (Dead) by L.Rs. v. Andhra Bank Ltd.' (12214027), a Constitution Bench judgment.

**Source span:** "P.S. Sathappan (Dead) by L.Rs. v. Andhra Bank Ltd. and Ors."

**Source doc_ids:** 1528427, 12214027  ·  **expected:** `answer`

_Verify:_ 1528427.cited_judgements contains 12214027; both in corpus.

### Q050 · medium · 2 hop(s)

**Q:** Which Supreme Court decision on interest does the ONGC judgment rely on?

**Gold answer:** It relies on 'Central Bank of India vs. Ravindra And Others', (2002) 1 SCC 367 (doc 1902234).

**Source span:** "Central Bank of India vs. Ravindra And Others"

**Source doc_ids:** 105140378, 1902234  ·  **expected:** `answer`

_Verify:_ 105140378.cited_judgements contains 1902234; both in corpus.

## Temporal / amendment

### Q047 · medium · 1 hop(s)

**Q:** When was Section 12A inserted into the CPC and by which amendment?

**Gold answer:** Section 12A was inserted by the Code of Civil Procedure (Amendment) Act, 1976 (Section 70), with effect from 1 February 1977.

**Source span:** "Section 70 (w.e.f. 1.2.1977)"

**Source doc_ids:** 40166762  ·  **expected:** `answer`

_Verify:_ Amendment note at end of Section 12A body.

### Q048 · medium · 1 hop(s)

**Q:** What is the pecuniary threshold in Section 102 CPC, and how was it modified for Uttar Pradesh?

**Gold answer:** Section 102 bars a second appeal where the money sought does not exceed twenty-five thousand rupees; for Uttar Pradesh this was substituted with 'fifty thousand rupees' by U.P. Act 16 of 2019.

**Source span:** "the words "fifty thousand rupees" shall be substituted. [U.P. act 16 of 2019]"

**Source doc_ids:** 114551302  ·  **expected:** `answer`

_Verify:_ UP state amendment note in Section 102 body.

## Negative · must abstain

### Q051 · medium · 0 hop(s)

**Q:** What is the punishment for murder under Section 302 of the Indian Penal Code?

**Gold answer:** Not answerable from this corpus. The corpus is limited to the Code of Civil Procedure, 1908 and civil judgments; it contains no Indian Penal Code provisions. The system should abstain.

**Source doc_ids:** — (none; abstain)  ·  **expected:** `abstain`

_Verify:_ Out-of-domain (criminal law); no IPC documents in corpus.

### Q052 · medium · 0 hop(s)

**Q:** What does Section 500 of the Code of Civil Procedure, 1908 provide?

**Gold answer:** Not answerable. There is no Section 500 in the CPC, 1908, and no such provision exists in the corpus. The system should abstain rather than fabricate text.

**Source doc_ids:** — (none; abstain)  ·  **expected:** `abstain`

_Verify:_ Non-existent provision; trap for hallucination.

### Q053 · medium · 0 hop(s)

**Q:** Summarize the Supreme Court's 2027 ruling on cryptocurrency taxation.

**Gold answer:** Not answerable. The corpus ends in mid-2026 and contains no cryptocurrency-taxation judgment; the system should abstain.

**Source doc_ids:** — (none; abstain)  ·  **expected:** `abstain`

_Verify:_ Out-of-period and out-of-domain.

### Q054 · medium · 0 hop(s)

**Q:** What bail conditions under Section 437 CrPC are discussed in the corpus judgments?

**Gold answer:** Not answerable. The corpus is civil (CPC) and contains no Criminal Procedure Code material or bail discussion; the system should abstain.

**Source doc_ids:** — (none; abstain)  ·  **expected:** `abstain`

_Verify:_ Out-of-domain (criminal procedure).

