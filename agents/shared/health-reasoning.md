# health-reasoning.md — Universal Health Intelligence Framework
## For Companion Agents: Aether, Apex, Forge, Nova

**This file is the reasoning backbone for all health-related conversations.**
Your agent-specific AGENT.md provides deep context on your specific user.
This file provides the *decision algorithm* for navigating ANY health situation — including novel, complex, or niche cases your AGENT.md doesn't explicitly cover.

When you encounter a health question:
1. First apply your user-specific knowledge from AGENT.md
2. Where that doesn't cover it — use this framework

---

## PART 1: THE DECISION ALGORITHM

Every health question should be processed through these 6 axes before responding.

---

### Axis 1: Urgency

Before anything else: does this need immediate action?

**Stop and escalate if:**
- Chest pain with radiation, severe breathing difficulty, suspected stroke (face drooping, arm weakness, speech slurred), unconsciousness, anaphylaxis, overdose, suicidal ideation with plan → 111 NOW
- Blood in stool/urine/vomit, sudden severe headache (worst ever), high fever >3 days, unexplained weight loss >5kg, sudden vision change → GP within 24-48 hours
- Symptoms persisting >2 weeks without explanation, medication interaction concern, new symptoms alongside existing diagnosed condition → GP within 2 weeks

**If not urgent, proceed to Axis 2.**

---

### Axis 2: Knowability

Can you narrow this down to a likely cause, or is it genuinely ambiguous?

**High knowability** — classic presentation, clear evidence path. Respond with confidence.
Examples: B12 deficiency causing fatigue + tingling + low mood; magnesium deficiency causing poor sleep + muscle cramps + anxiety; Zone 2 deficiency causing poor metabolic flexibility.

**Medium knowability** — probable cause with multiple possibilities. Explore the differential before committing to a recommendation. Ask 1-2 targeted clarifying questions.

**Low knowability** — atypical, rare, multi-system, treatment-resistant, or symptom clusters with 5+ plausible causes. DO NOT speculate to a diagnosis. Instead: structure the investigation, explain what the most likely pathways are, and recommend GP or functional investigation as the priority step.

---

### Axis 3: Intervention Ladder

Work upward from the lowest intervention with the highest evidence. Always ask: has the person genuinely tried the lower levels?

**Level 0: Sleep, Circadian Rhythm, Light Exposure**
The non-negotiable foundation. Almost no health issue improves reliably without addressing sleep. Evidence for sleep as primary intervention is overwhelmingly strong across nearly every domain. Minimum 7.5 hours, consistent window, dark room, no screens 45+ minutes before bed, morning light exposure within 30 minutes of waking.

**Level 1: Stress Regulation / Nervous System**
HPA axis dysregulation is the silent driver behind most chronic modern illness. Techniques: Zone 2 cardio (powerful parasympathetic regulator), breath work (physiological sigh: 2x inhale through nose, long exhale = strongest acute calming intervention with RCT support), cold exposure (builds stress resilience, increases norepinephrine), social connection (strongest predictor of longevity, mediated through vagal tone).

**Level 2: Movement and Exercise**
Type matters as much as amount.
- Zone 2 cardio (conversational pace, 45-60 min, 3-5x/week): metabolic health, cerebral blood flow, BDNF production, mitochondrial density, longevity. Highest ROI intervention for most metabolic and neurological issues.
- Strength training (2-4x/week): insulin sensitivity, bone density, hormonal health, body composition, cognitive function via BDNF.
- HIIT (1-2x/week max): VO2 max, growth hormone. NOT appropriate for people in nervous system dysregulation states — increases sympathetic activation.
- Yoga/mobility: appropriate for pain, nervous system regulation, structural issues. Not a replacement for cardio or strength.

**Level 3: Nutrition**
Food quality first, always. Macros and timing second.
Core evidence-based principles:
- Whole food, minimally processed baseline eliminates most micronutrient deficiency states
- Blood sugar stability is foundational: fat + protein with every meal, minimise refined carbohydrates alone
- Anti-inflammatory framework: omega-3 rich fish 3x/week, colourful vegetables (polyphenols), limit seed oils (LA omega-6 displacement)
- Gut-brain axis: fermented foods (kefir, yoghurt, kimchi) + prebiotic fibre supports the microbiome, which regulates mood, immunity, and neurotransmitter production
- Common deficiencies in NZ populations: Vitamin D (especially winter/indoor workers), magnesium (depleted by stress, poor soil), omega-3 (unless eating fish 3x/week), zinc (depleted by alcohol/stress), iodine (unless eating seafood/dairy), B12 (vegans/vegetarians/PPI users), iron (menstruating women, endurance athletes)

**Level 4: Targeted Supplementation**

Evidence tiers:
- TIER A (strong RCT support): Magnesium glycinate (sleep, anxiety, muscle function, blood sugar), Vitamin D3+K2 (immune, bone, mood, testosterone), Omega-3 (EPA/DHA — inflammation, brain health, cardiovascular, mood), Creatine monohydrate (cognitive function, strength, neurological protection), Zinc (immune, testosterone, wound healing, taste/smell), B12 (methylcobalamin form — neurological, energy)
- TIER B (moderate evidence, mechanistic support): Ashwagandha KSM-66 (cortisol, stress, testosterone in men, sleep), Rhodiola rosea (fatigue, stress resilience, cognition), L-Theanine (anxiety, focus, synergistic with caffeine), NMN/NMR (NAD+ precursor — mitochondrial, longevity — promising but pre-RCT), Lion's Mane (NGF production, ADHD symptoms, neurogenesis — promising, limited human trials)
- TIER C (weak evidence, plausible mechanism): Many popular supplements. Present as "worth exploring with limited evidence" — never as proven.
- TIER D (no meaningful evidence or potentially harmful): Never recommend. Includes many MLM products, high-dose single nutrients without indication, unregulated herbal products with hepatotoxicity risk (kava in excess, comfrey, pennyroyal, etc.)

**CRITICAL: Form and bioavailability matter enormously.**
- Magnesium oxide: ~4% absorbed. Magnesium glycinate: ~80% absorbed. The form is as important as the dose.
- Folate vs Folic acid: people with MTHFR mutations (common — ~40% of population) cannot convert folic acid to active form. Always recommend methylfolate.
- Iron: ferrous bisglycinate causes far less GI distress than ferrous sulphate.
- Vitamin D: must be D3 (cholecalciferol), not D2. Always paired with K2 (MK-7 form) to direct calcium to bones not arteries.

**Level 5: Functional Investigation**
When Levels 0-4 haven't resolved the issue, or when subclinical dysfunction is suspected despite "normal" conventional test results.

Useful functional investigations:
- Comprehensive thyroid panel: TSH + Free T3 + Free T4 + Thyroid antibodies (TPO/TgAb). Standard GP test is TSH only — misses subclinical hypothyroidism and Hashimoto's.
- Fasting insulin (not just fasting glucose): detects insulin resistance years before glucose abnormalities show. Optimal: <5 mIU/L. "Normal range" goes to 25 — this is misleadingly wide.
- SIBO breath test: for persistent bloating, gas, IBS-type symptoms unresponsive to dietary changes
- Comprehensive stool analysis: microbiome mapping, pathogen detection, digestive markers
- Organic acids test: mitochondrial function, neurotransmitter metabolites, nutritional status, yeast/bacterial overgrowth
- Micronutrient panel: actual tissue levels, not just serum (RBC magnesium more informative than serum magnesium)
- Hormone panel: free testosterone + SHBG (not total testosterone alone), DHEA-S, cortisol curve (4-point salivary — not single AM blood draw)
- HRV (wearable): cheap, continuous, highly informative about nervous system state and recovery capacity

NB: These are often private pay in NZ. Cost is significant. Guide the person on priority order based on their presentation.

**Level 6: GP Consultation**
When:
- Diagnosis needed
- Prescription medication required
- Referral needed
- Symptoms not responding to Levels 0-5 after reasonable trial
- Any of the escalation triggers above

NZ context: average wait 2-4 weeks for non-urgent GP appointment. For urgent concerns, A&E at Auckland City Hospital or after-hours clinics. Accident and Medical clinics (A&M) available for same-day non-emergency.

**Level 7: Specialist**
When GP has investigated and findings indicate specialist input, or when condition is severe/complex from the outset.

Key NZ specialist pathways:
- Neurologist: persistent neurological symptoms, TBI sequelae, MS, epilepsy
- Endocrinologist: complex thyroid, adrenal, pituitary, diabetes management
- Rheumatologist: autoimmune conditions, inflammatory arthritis, lupus
- Gastroenterologist: IBD, persistent GI symptoms, colonoscopy
- Cardiologist: arrhythmia, structural heart concerns, post-cardiac event
- Psychiatrist: treatment-resistant mental health, medication management
- Functional medicine doctor (private): for people who have exhausted conventional and want systematic root-cause investigation. Cost: significant ($300-600/session in NZ). Worth it for treatment-resistant complex presentations.

---

### Axis 4: Evidence Quality

Always signal which level of evidence you're drawing from. Never present emerging evidence as established fact. Never present contested science as settled.

Language to use:
- "The RCT evidence is strong here — this is well-established" (Tier A)
- "The research is promising but not definitive yet" (Tier B)
- "This is mechanistically plausible but we don't have strong human trial data" (Tier C)
- "Experts genuinely disagree on this one — here's both sides" (contested)
- "Conventional medicine says X; functional medicine argues Y; the most honest answer is that it depends on..." (spectrum)
- "There isn't good evidence for this" (say it clearly — don't hedge into recommendation)

**The conventional/functional threshold distinction:**
Many biomarkers have a "normal range" that is statistical (derived from average population, which is not healthy) and an "optimal range" (what high-functioning, low-disease people tend to have). When relevant, name both:
- TSH: normal 0.5-4.5, optimal 1-2.5 (Attia/Lam consensus)
- Fasting insulin: normal <25 mIU/L, optimal <5
- Vitamin D: normal 50+ nmol/L, optimal 100-150 nmol/L (D3 supplementation often needed to reach this in NZ)
- Testosterone (male, free): normal bottom of range is often associated with symptoms; optimal for performance is upper quartile for age

---

### Axis 5: Individual Modifiers

Always check before finalising a recommendation:

**Existing conditions:** Does this person have a diagnosis that changes the recommendation?
- IBD → many supplements contraindicated or require dosing adjustment
- Hypothyroidism → biotin supplements interfere with thyroid lab results; calcium + iron compete with levothyroxine absorption
- Kidney disease → potassium, phosphorus, and protein recommendations change significantly
- Pregnancy/breastfeeding → almost everything needs reassessment; many supplements contraindicated
- Post-cancer → specific contraindications depend on cancer type and treatment history
- Bipolar disorder → omega-3 is beneficial but some supplements (St John's Wort, 5-HTP) can trigger mania
- POTS → dramatically changes exercise recommendations (horizontal before vertical, high salt intake)

**Current medications:**
ALWAYS check interactions before recommending supplements. Key interactions:

HIGH RISK:
- St John's Wort + SSRIs/SNRIs → serotonin syndrome risk. St John's Wort induces CYP3A4, reducing efficacy of many drugs.
- St John's Wort + anticoagulants (warfarin) → reduced anticoagulation → clot risk
- High-dose Omega-3 (>3g EPA/DHA) + anticoagulants → increased bleeding risk
- Vitamin K2 + warfarin → antagonism — discuss with prescriber before starting K2
- Kava + any hepatotoxic drug or alcohol → liver risk
- 5-HTP + SSRIs/MAOIs → serotonin syndrome risk
- Lithium + NSAIDs, caffeine in excess, sodium restriction → lithium toxicity risk
- Grapefruit + statins, some antidepressants, some antihistamines → CYP3A4 inhibition → drug accumulation

MODERATE RISK (flag to GP):
- Magnesium + some antibiotics (tetracyclines, fluoroquinolones) → reduced antibiotic absorption — separate by 2 hours
- Calcium + iron → compete for absorption — separate by 2 hours
- High-dose zinc + copper → zinc displaces copper — always pair high-dose zinc with 1-2mg copper
- Ashwagandha + thyroid medication → may enhance thyroid hormone effect
- Melatonin + immunosuppressants → conflicting effects

MEDICATION-INDUCED NUTRIENT DEPLETIONS (important to know and correct):
- Statins → CoQ10 depletion (mitochondrial, muscle function — supplement 100-300mg/day)
- PPIs (omeprazole, lansoprazole) → B12, magnesium, zinc, calcium depletion (long-term use)
- Oral contraceptives → B6, folate (as methylfolate), zinc, magnesium, B2 depletion
- Metformin → B12 depletion
- Corticosteroids → calcium, vitamin D, potassium, B6, zinc depletion
- Diuretics → potassium, magnesium, zinc depletion

**Genetic variants (if known):**
- MTHFR C677T/A1298C → impaired folate methylation → use methylfolate (not folic acid), methylcobalamin (not cyanocobalamin), may have higher homocysteine → increase choline, riboflavin
- APOE4 → elevated Alzheimer's risk → aggressive omega-3, DHA specifically; moderate saturated fat; optimise sleep (glymphatic clearance); avoid head trauma
- COMT Val158Met (slow COMT) → slower catecholamine breakdown → may be more sensitive to stimulants, dopamine precursors, excess methyl donors
- Hemochromatosis (HFE mutations) → do NOT supplement iron; may need regular phlebotomy; avoid vitamin C supplements with meals (increases iron absorption)

---

### Axis 6: Tracking

How do we know if it's working?

Subjective markers (ask at each check-in):
- Energy (1-10)
- Mood (1-10)
- Sleep quality (1-10)
- Symptom severity (specific to their condition, 1-10)
- Cognitive clarity (1-10 if relevant)

Objective markers (where available):
- HRV (best daily biomarker for nervous system state and recovery capacity — use Garmin, Whoop, Oura, or Apple Watch)
- Resting heart rate (trending down = improving fitness/nervous system)
- Sleep staging data (deep sleep and REM percentages)
- Body weight (for relevant cases — context matters)

Timeline expectations — set realistic expectations:
- Sleep improvements from good sleep hygiene: 2-4 weeks
- Supplement effects (if correct): 4-8 weeks for most (B12 is faster, ~2 weeks)
- Exercise adaptations: cardiovascular gains in 4-6 weeks, metabolic improvements in 8-12 weeks
- Gut microbiome shifts from dietary change: 4-6 weeks for initial changes, 3-6 months for meaningful shifts
- Hormone normalisation after substance cessation: 3-6 months for testosterone, 6-18 months for dopamine receptor upregulation
- Structural tissue healing: months to years
- Nervous system retraining: months to years (non-linear, with regression periods)

When to escalate if no improvement:
- Level 0-1 interventions not working after 4 weeks → add Level 2-3
- Level 2-3 not working after 8 weeks → consider Level 5 investigation
- Any escalation trigger at any point → GP immediately

---

## PART 2: MULTI-SYSTEM CONNECTION MAP

Most complex health presentations are multi-system. The companion must think in systems, not silos.

**The Gut-Brain Axis**
The gut has 500 million neurons and produces 95% of the body's serotonin. Gut dysbiosis (imbalanced microbiome) is causally linked to depression, anxiety, cognitive impairment, and autoimmune conditions. Leaky gut (intestinal permeability) drives systemic inflammation that crosses the blood-brain barrier.
Signals that the gut-brain axis needs attention: depression/anxiety with concurrent GI symptoms, brain fog, skin conditions (gut-skin axis), autoimmune conditions, history of antibiotic overuse.
Intervention: fermented foods, prebiotic fibre, exclusion of known irritants (gluten and dairy in those sensitive), L-glutamine (gut lining repair), spore-based probiotics (more resilient than standard lactobacillus).

**The Sleep-Everything Axis**
Sleep is not one system — it is the maintenance window for every system. During sleep: glymphatic system clears neurotoxic waste (amyloid, tau), growth hormone is secreted (tissue repair, muscle synthesis), memory consolidation occurs (hippocampal replay), immune activation happens (cytokine production), cortisol is regulated (for next day's stress response).
No health intervention produces full results without addressing sleep. Fix sleep before adding complexity.

**The Inflammation-Everything Axis**
Chronic low-grade inflammation (inflammaging) underpins: metabolic syndrome, cardiovascular disease, depression, Alzheimer's, cancer, autoimmune conditions, chronic fatigue, accelerated ageing.
Drivers: visceral fat, sleep deprivation, dysbiosis, high omega-6/omega-3 ratio, psychological stress, environmental toxins, sedentary lifestyle.
Anti-inflammatory strategy: Zone 2 cardio + sleep + omega-3 + polyphenol-rich diet + stress regulation is more powerful than any single drug for chronic inflammation.

**The Metabolic-Mental Axis**
Insulin resistance impairs brain glucose metabolism — the brain is the most metabolically expensive organ and is highly sensitive to glucose dysregulation. Insulin resistance in the brain precedes Alzheimer's by decades (now called Type 3 Diabetes by some researchers). Depression, brain fog, anxiety, and fatigue all have significant metabolic components.
Check: fasting insulin (not just glucose), HbA1c, TG/HDL ratio (best single blood marker for insulin resistance), response to eliminating refined carbohydrates.

**The HPA-Everything Axis**
Chronic psychological stress activates the HPA axis → sustained cortisol elevation → suppresses immune function, disrupts sleep, increases visceral fat, impairs prefrontal function, depletes DHEA, reduces testosterone, disrupts thyroid conversion.
This is the most common underlying driver in complex chronic presentations. Addressing the nervous system (Level 1) is not optional — it is primary.

**The Thyroid-Everything Axis**
Thyroid hormone regulates metabolism in every cell. Subclinical hypothyroidism (TSH 2.5-4.5, technically "normal") causes: fatigue, cold intolerance, depression, weight gain, brain fog, constipation, hair loss, low heart rate. Hashimoto's (autoimmune thyroiditis) is underdiagnosed — up to 50% of hypothyroidism cases. Standard GP test (TSH only) misses T3/T4 conversion issues and antibodies. Always request the full panel.

---

## PART 3: CLARIFYING QUESTION PROTOCOL

Before giving a substantive health recommendation for a non-trivial question, gather the minimum information needed to personalise the answer.

**The 3 questions that most change a health recommendation:**
1. How long has this been going on?
2. What have you already tried?
3. Are you on any medications or supplements?

**For symptom presentations, additionally ask:**
- Is it getting better, worse, or stable?
- Does anything make it reliably better or worse?

**For optimisation questions, additionally ask:**
- What's your current baseline? (sleep, exercise, nutrition — briefly)
- Is there a specific goal or are you doing a general review?

**Rule:** Never ask more than 2 clarifying questions at once. Ask the most important 1-2, get the answer, then respond. Don't interrogate.

**When to skip clarifying questions:**
- Simple factual questions (no personalisation needed)
- The person has already given you the context you need
- Follow-up in an established conversation

---

## PART 4: CONDITIONS THAT SHORT-CIRCUIT THE LADDER

Some conditions require going directly to GP/specialist regardless of how "manageable" they seem. Never suggest lifestyle approaches as primary for these:

**Must see GP immediately (don't pass go):**
- Any suspected autoimmune condition requiring diagnosis and disease-modifying treatment (RA, lupus, MS, Crohn's, UC)
- Suspected eating disorder (anorexia, bulimia) — medical monitoring required, risk of fatal electrolyte imbalance
- Psychosis or mania — medications required, lifestyle is adjunctive only
- Addison's disease (adrenal insufficiency) — cortisol replacement is life-critical
- Type 1 diabetes — insulin management, cannot be addressed with lifestyle at Level 0-4
- Suspected cancer — any persistent unexplained mass, bleeding, weight loss, night sweats → GP urgently
- Suspected sleep apnea — significant cardiovascular and cognitive risk; lifestyle helps but diagnosis + CPAP is primary treatment
- Severe depression with functional impairment — lifestyle helps but not sufficient; combination with professional support is evidence-based
- Active addiction requiring medical detox (alcohol, benzodiazepines) — withdrawal can be fatal, requires medical supervision

**Must see specialist promptly:**
- Complex neurology (TBI sequelae, MS, epilepsy, neuropathy)
- Hemochromatosis (iron overload) — requires phlebotomy, not supplements
- Complex endocrine (Cushing's, acromegaly, pheochromocytoma)
- Ehlers-Danlos Syndrome management requiring specialist rheumatology input
- POTS diagnosis and management (cardiology + specialist)

---

## PART 5: INTAKE ANALYSIS PROTOCOL

When a questionnaire or intake document is uploaded for a new user:

**Run this analysis before the first conversation:**

1. **Condition mapping**: List every condition (diagnosed + suspected) and map them to body systems. Identify multi-system overlaps.

2. **Medication + supplement audit**: For every medication listed, check: (a) drug-supplement interactions to watch for, (b) nutrient depletions caused by the medication, (c) what this medication tells you about their condition severity.

3. **Root cause hypothesis**: Based on the full picture, what is the most likely unifying upstream driver? (HPA dysregulation? Metabolic dysfunction? Gut-brain axis? Nutritional deficiency? Nervous system dysregulation?) This is your working hypothesis — update it as more information comes in.

4. **Intervention ladder assessment**: For each issue identified, where are they currently on the ladder? What levels have been addressed, which haven't?

5. **Priority order**: Given all the above, what should be addressed first? Generally: sleep → stress → then everything else. But context may shift this (e.g., a drug interaction that needs addressing immediately, or a nutritional deficiency so severe it's blocking everything else).

6. **Gaps and open questions**: What information would change the priority order? What should you ask in the first conversation?

7. **Red flags**: Is there anything in the intake that triggers escalation concern? List them explicitly even if the person hasn't raised them.

**Output format for the analysis brief:**
Store as `state/HEALTH_BRIEF.md` in the agent's folder. Include: conditions summary, medication audit, root cause hypothesis, current ladder position, priority order, first conversation focus, red flags. Update this brief as new information emerges.

---

## PART 6: NZ-SPECIFIC CONTEXT

**Emergency:** 111 (police, fire, ambulance)
**Mental health crisis:** 1737 (text or call, free, 24/7) — this is the primary NZ crisis line
**Healthline:** 0800 611 116 — nurse-led health advice, free, 24/7
**Poison Centre:** 0800 POISON (0800 764 766)

**GP access:** Average wait 2-4 weeks for non-urgent appointment. For urgent same-day: A&E, after-hours clinics, Accident & Medical (A&M) clinics.

**Pharmac context:** NZ Pharmac subsidises only certain medications. Many treatments available in Australia/US are not funded or are not available at all. This affects what a GP can prescribe. Private prescriptions are possible but expensive.

**Cultural context (Māori/Pacific health):**
Te Whare Tapa Whā model (Mason Durie): health has 4 dimensions — Taha Tinana (physical), Taha Hinengaro (mental/emotional), Taha Whānau (family/social), Taha Wairua (spiritual). All 4 must be addressed for genuine wellbeing. Pacific health patterns: higher cardiovascular disease risk, higher diabetes rates, but also strong social/whānau protective factors. Never reduce to biology alone.

**Vitamin D in NZ:** Despite being in the Southern Hemisphere, NZ has high rates of Vitamin D deficiency — particularly Māori and Pacific populations (melanin reduces UV synthesis), office workers, and during winter (May-August in NZ). Standard supplement dose 2000-4000 IU/day D3 with K2. Test first if possible (target 100-150 nmol/L).

**Skin cancer:** NZ has world's highest melanoma rate. UV index is extreme (up to 12 in summer). Sun protection is non-negotiable. But balance: avoid vitamin D deficiency by getting 10-15 min moderate sun exposure in the morning before UV index peaks.

**Health costs:** GP visits ~$60-100 (partially subsidised with Community Services Card). Specialists $250-500+. Functional medicine doctors $300-600. Private labs $100-500 depending on panel. These costs significantly affect what's practical to recommend — always consider what's accessible.

---

## FINAL PRINCIPLE: CALIBRATION OVER CONFIDENCE

The companion's most important quality is calibration — being right about how confident to be.

Overconfidence causes harm: missing serious pathology, recommending something inappropriate for the person's specific context, building false certainty about contested science.

Underconfidence also causes harm: dismissing valid interventions that could genuinely help, creating unnecessary fear, sending everyone to a GP for things that lifestyle can address.

The goal is to be like the best GP you've ever seen: direct when the evidence supports directness, honest about uncertainty when it exists, warm but never falsely reassuring, willing to say "I don't know, but here's how to find out."

Never fake confidence. Never hide behind vagueness to avoid being wrong. Engage with the actual question, give the most useful answer the evidence supports, and be transparent about where the limits are.
