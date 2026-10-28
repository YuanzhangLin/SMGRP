"""Prompts for the two-stage MGRP planner."""

ANALYZE_SYSTEM = """You construct an ordered knowledge chain for an Android GUI task from the task,
the supplied UI Map, and conservative general GUI knowledge. Return one JSON object. Separate what
the Map explicitly supports from plausible general knowledge. A gap is a critical chain link whose
app-specific target, trigger, effect, scope, or commit semantics remain unsupported or ambiguous.
Do not treat a missing literal button in the Map as a plan gap when the chain already has a coherent,
high-confidence Map-supported action. Keep requirements semantic and plan-oriented.
The initial plan is the complete task-level operation skeleton, not merely the subset already proven
by repository evidence. Preserve every explicit task goal, target value, polarity (enable/disable,
add/remove, ascending/descending), terminal action, and semantically necessary commit. Record
uncertainty as a gap without deleting the corresponding required action from the initial plan.
Allowed gap_type values: missing_target, missing_trigger, missing_transition, missing_effect,
ambiguous_scope, missing_commit, missing_verification. If evidence is sufficient, return no gaps."""

ANALYZE_USER = """Task: {instruction}

UI MAP EXCERPT:
{ui_map}

TASK-RELEVANT UI–CODE ANCHORS:
{anchors}

Return:
{{
  "requirements": [{{"id":"R1","type":"navigation|execution|parameter|commit|verification","goal":"...","critical":true}}],
  "knowledge_chain": [{{
    "id":"K1", "requirement_id":"R1", "role":"state|action|effect|parameter|commit|verification",
    "proposition":"a concise GUI fact or action link",
    "support":"map_explicit|map_inferred|common_gui_knowledge|unsupported|ambiguous",
    "map_evidence":["visible label, resource id, activity or transition"], "confidence":0.0
  }}],
  "initial_plan": ["one user-visible action per item"],
  "gaps": [{{"requirement_id":"R1","gap_type":"missing_trigger","description":"...","query_terms":["..."],"preferred_artifacts":["menu_xml","handler"]}}],
  "confidence": 0.0
}}
Treat an anchor with a visible target, container, and handler as grounded Map support. Create gaps
only for critical unsupported or ambiguous links. Every literal task value (names, dates, folders,
countries, filenames, counts, and option values) must have its own parameter requirement and chain
link. Before returning, verify that every critical requirement appears as an executable action in
initial_plan, even when that action is also marked as a gap. Interaction-semantic anchors are constraints: for changing or renaming an existing dynamic
item, prefer ordinary_click/edit_existing_item and its update commit; never substitute
selection_or_long_press/delete_existing_item followed by creating a new item. Do not invent a
verification requirement unless the task explicitly asks for verification or
the action semantics require an observable commit. Do not include source-code edits or
implementation actions in initial_plan. Every initial_plan item must be directly executable by a
user: never say "navigate to XActivity". Name the visible control, and when a menu item lives in an
overflow container, emit opening More options as a separate preceding action. Unless the task
explicitly supplies a starting state, begin at the app's main/default screen; never assume the user
already occupies an intermediate destination such as Settings."""

GROUND_SYSTEM = """You complete an Android GUI knowledge chain with local repository evidence and
then render it as a plan. Return one JSON object. Treat ANALYSIS.initial_plan as an ordered, lossless
operation scaffold. Preserve its supported actions and use repository snippets only to refine or
complete unsupported or ambiguous links. Translate code facts into exact user-visible
actions; never expose method names as actions. Distinguish opening an overflow menu, selecting an item,
confirming a dialog, and pressing Back while preserving state. Do not add a generic confirmation when
the evidence only supports selection or return. Every critical requirement must be explicit. Prefer
exact visible labels and resource-backed actions. Do not regenerate or weaken already supported links.
Repository search failure is not evidence that a required action is absent. Never remove an initial
action unless retrieved evidence explicitly contradicts it. When a semantically necessary terminal
action remains unresolved, retain a concise user-visible action with the most specific label supported
by the Map or task and report the residual uncertainty in unresolved_gaps."""

GROUND_USER = """Task: {instruction}

ANALYSIS:
{analysis}

LOCAL REPOSITORY EVIDENCE:
{evidence}

Return:
{{
  "grounded_knowledge_chain": [{{"id":"K1","proposition":"...","support":"map|repository|common","evidence":["path:line"]}}],
  "steps": ["one concise user-visible action per item"],
  "requirement_coverage": [{{"requirement_id":"R1","step_numbers":[1],"supported":true,"evidence":["path:line"]}}],
  "unresolved_gaps": ["..."],
  "confidence": 0.0
}}
Honor interaction-semantic anchors as hard constraints. Editing an existing item is not equivalent
to deleting it and creating a replacement. Do not silently replace an unsupported workflow with a
plausible alternative. Before returning, audit the task and every critical requirement in ANALYSIS:
each must be represented by at least one step and one requirement_coverage entry. Preserve task
polarity and exact parameter values. Evidence may add specificity, but it must not shorten the plan
by dropping navigation, the requested operation, or a necessary commit from the initial scaffold."""
