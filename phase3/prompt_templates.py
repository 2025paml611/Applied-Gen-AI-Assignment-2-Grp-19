"""
prompt_templates.py - 5 Prompt Ablation Variants with Metadata Ontology
Course: PCAM* ZG516 - Applied Generative AI (Major Project / Assignment 2)
Phase 3: Security Guardrails, Prompt Ablation & Self-Improving Loop
Satisfies: Experiment E7, Task A5
"""

import os
from typing import List, Dict, Any

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    from jinja2 import Template
    HAS_JINJA = True
except ImportError:
    HAS_JINJA = False

def find_ontology_file() -> str:
    candidates = [
        "data/ontology.yaml",
        "../data/ontology.yaml",
        os.path.join(os.path.dirname(__file__), "..", "data", "ontology.yaml")
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "data/ontology.yaml"

def load_ontology() -> dict:
    onto_path = find_ontology_file()
    if os.path.exists(onto_path) and HAS_YAML:
        with open(onto_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {
        "ontology_name": "RBI_Regulatory_Corpus_Ontology",
        "prompt_routing_rules": {
            "table_priority_keywords": ["ratio", "percentage", "rate", "threshold", "capital", "limit", "bps", "spread"],
            "image_priority_keywords": ["corridor", "diagram", "chart", "workflow", "process flow", "architecture", "timeline"],
            "strict_grounding_clause": "Answer strictly based on cited RBI circulars and slides. If evidence is absent, declare refusal."
        }
    }

ONTOLOGY = load_ontology()

# 1. Zero-Shot Baseline
def render_zero_shot(query: str, context: str) -> str:
    return f"""Answer the question based only on the context below.
Context:
{context}

Question: {query}
Answer:"""

# 2. F-String Prompt (Simple Role + Constraint)
def render_fstring(query: str, context: str) -> str:
    return f"""You are an RBI Regulatory Compliance Assistant.
Answer the user's query truthfully using only the provided context snippets.
Cite the source document and page number in the format [Source: <filename>, Page/Slide: <number>].
If the context does not contain the answer, state: "Insufficient evidence in provided documents."

Retrieved Regulatory Context:
{context}

User Question: {query}
Compliance Answer:"""

# 3. Three-Shot Few-Shot Prompt
def render_three_shot(query: str, context: str) -> str:
    return f"""You are an RBI Regulatory Compliance Assistant. Follow the exact style and citation rules of the examples.

Example 1:
Context: [RBI_Presentation_Monetary_Policy_Framework_2024.pptx, Slide 2]: The MPC statutory inflation target is 4.0% headline CPI with a tolerance band of +/- 2%.
Question: What is the statutory inflation target?
Answer: The statutory inflation target is 4.0% headline CPI with a tolerance band of +/- 2% (2.0% to 6.0%) [Source: RBI_Presentation_Monetary_Policy_Framework_2024.pptx, Page/Slide: 2].

Example 2:
Context: [RBI_Presentation_Scale_Based_Regulation_NBFCs.pptx, Slide 3]: NBFCs with asset size below Rs 1,000 crore reside in the Base Layer. Assets >= Rs 1,000 crore form the Middle Layer.
Question: What is the asset threshold for NBFC Middle Layer?
Answer: The asset threshold for the NBFC Middle Layer is Rs 1,000 crore and above [Source: RBI_Presentation_Scale_Based_Regulation_NBFCs.pptx, Page/Slide: 3].

Example 3:
Context: [2025-11-28_Master-Direction_13096.pdf, Page 12]: No deposit shall be accepted without completing Customer Due Diligence.
Question: Can interest rates be negative?
Answer: Insufficient evidence in provided documents.

Now answer:
Context:
{context}

Question: {query}
Answer:"""

# 4. Jinja2 Templated Prompt (Ontology-Driven)
JINJA_STR = """
## SYSTEM GOVERNANCE & METADATA ONTOLOGY
Ontology: {{ ontology.ontology_name }}
Strict Rule: {{ ontology.prompt_routing_rules.strict_grounding_clause }}

## ROUTING HEURISTICS
- Table Priorities: {{ ontology.prompt_routing_rules.table_priority_keywords | join(', ') }}
- Visual/Diagram Priorities: {{ ontology.prompt_routing_rules.image_priority_keywords | join(', ') }}

## RETRIEVED MULTIMODAL CONTEXT
{% for chunk in chunks %}
[{{ chunk.modality | upper }} | Doc: {{ chunk.doc_name }} | Page/Slide: {{ chunk.page_or_slide }}]
{{ chunk.content }}
--------------------------------------------------
{% endfor %}

## USER INQUIRY
{{ query }}

## INSTRUCTIONS
1. Synthesize an answer grounded solely in the excerpts above.
2. Every substantive assertion must cite its source exactly: [Source: <doc_name>, Page/Slide: <page_or_slide>].
3. For table or numerical limits, reproduce exact regulatory figures without rounding.
4. If no excerpt confirms the answer, output: "Insufficient evidence in provided documents."
Answer:
"""

def render_jinja2_ontology(query: str, chunks: list) -> str:
    if HAS_JINJA:
        tmpl = Template(JINJA_STR)
        return tmpl.render(ontology=ONTOLOGY, chunks=chunks, query=query)
    
    chunks_rendered = "\n".join([
        f"[{c.get('modality', 'TEXT').upper()} | Doc: {c.get('doc_name')} | Page/Slide: {c.get('page_or_slide')}]\n{c.get('content')}\n" + "-"*50
        for c in chunks
    ])
    tbl_kw = ", ".join(ONTOLOGY["prompt_routing_rules"]["table_priority_keywords"])
    img_kw = ", ".join(ONTOLOGY["prompt_routing_rules"]["image_priority_keywords"])
    rule = ONTOLOGY["prompt_routing_rules"]["strict_grounding_clause"]
    
    return f"""## SYSTEM GOVERNANCE & METADATA ONTOLOGY
Ontology: {ONTOLOGY['ontology_name']}
Strict Rule: {rule}

## ROUTING HEURISTICS
- Table Priorities: {tbl_kw}
- Visual/Diagram Priorities: {img_kw}

## RETRIEVED MULTIMODAL CONTEXT
{chunks_rendered}

## USER INQUIRY
{query}

## INSTRUCTIONS
1. Synthesize an answer grounded solely in the excerpts above.
2. Every substantive assertion must cite its source exactly: [Source: <doc_name>, Page/Slide: <page_or_slide>].
3. For table or numerical limits, reproduce exact regulatory figures without rounding.
4. If no excerpt confirms the answer, output: "Insufficient evidence in provided documents."
Answer:"""

# 5. Structured Framework (CREATE Framework)
def render_create_framework(query: str, context: str) -> str:
    return f"""[ROLE]: Senior Reserve Bank of India (RBI) Regulatory Officer & Legal Auditor.
[CONTEXT]: Reviewing official Master Circulars, Master Directions, and policy briefing presentations.
[EXECUTION INSTRUCTIONS]:
1. Scan the context for explicit provisions addressing the user's question.
2. Validate whether text, quantitative tables, or diagram captions provide the necessary data.
3. Formulate a concise, definitive answer.
4. If evidence is ambiguous or missing, trigger immediate safe refusal.
[ACTION & CITATION CONTRACT]:
- Append [Source: <doc>, Page/Slide: <num>] after each finding.
- Do not make external assumptions or extrapolate beyond cited RBI text.

[RETRIEVED CONTEXT]:
{context}

[TARGET QUERY]:
{query}

[EVALUATION / COMPLIANCE RESPONSE]:"""
