import { z } from "zod";
import { tool } from "@langchain/core/tools";

// Common medical terms to MeSH mappings
const MESH_MAPPINGS: Record<string, string[]> = {
  // Diseases
  diabetes: ["Diabetes Mellitus", "Diabetes Mellitus, Type 2", "Diabetes Mellitus, Type 1"],
  hypertension: ["Hypertension", "Blood Pressure, High"],
  cancer: ["Neoplasms", "Carcinoma", "Malignant Neoplasms"],
  heart_disease: ["Heart Diseases", "Cardiovascular Diseases", "Coronary Disease"],
  stroke: ["Stroke", "Cerebrovascular Disorders"],
  alzheimer: ["Alzheimer Disease", "Dementia"],
  depression: ["Depression", "Depressive Disorder", "Depressive Disorder, Major"],
  anxiety: ["Anxiety", "Anxiety Disorders"],
  asthma: ["Asthma", "Respiratory Hypersensitivity"],
  copd: ["Pulmonary Disease, Chronic Obstructive", "COPD"],
  arthritis: ["Arthritis", "Arthritis, Rheumatoid", "Osteoarthritis"],
  obesity: ["Obesity", "Overweight"],
  pneumonia: ["Pneumonia", "Lung Diseases"],
  covid: ["COVID-19", "SARS-CoV-2", "Coronavirus"],
  periodontitis: ["Periodontitis", "Periodontal Diseases"],
  caries: ["Dental Caries", "Tooth Decay"],
  gingivitis: ["Gingivitis", "Gingival Diseases"],

  // Treatments
  metformin: ["Metformin", "Biguanides"],
  insulin: ["Insulin", "Insulin, Regular, Human"],
  sglt2: ["Sodium-Glucose Transporter 2 Inhibitors", "SGLT2 Inhibitors"],
  ace_inhibitor: ["Angiotensin-Converting Enzyme Inhibitors", "ACE Inhibitors"],
  statin: ["Hydroxymethylglutaryl-CoA Reductase Inhibitors", "Statins"],
  aspirin: ["Aspirin", "Anti-Inflammatory Agents, Non-Steroidal"],
  antibiotics: ["Anti-Bacterial Agents", "Antibiotics"],
  chemotherapy: ["Antineoplastic Agents", "Chemotherapy"],
  immunotherapy: ["Immunotherapy", "Immune Checkpoint Inhibitors"],
  surgery: ["Surgical Procedures, Operative", "General Surgery"],
  radiation: ["Radiotherapy", "Radiation Therapy"],

  // Populations
  elderly: ["Aged", "Aged, 80 and over", "Elderly"],
  children: ["Child", "Pediatrics", "Infant"],
  pregnant: ["Pregnancy", "Pregnant Women"],
  adults: ["Adult", "Middle Aged"],

  // Outcomes
  mortality: ["Mortality", "Death", "Survival Rate"],
  quality_of_life: ["Quality of Life", "Health-Related Quality of Life"],
  hospitalization: ["Hospitalization", "Patient Admission"],
  adverse_events: ["Adverse Effects", "Drug-Related Side Effects and Adverse Reactions"],
};

// Evidence level classification based on study type
export const EVIDENCE_LEVELS: Record<string, { level: string; description: string }> = {
  "meta-analysis": { level: "Level I", description: "Systematic review of RCTs or meta-analysis" },
  "systematic review": { level: "Level I", description: "Systematic review of RCTs" },
  rct: { level: "Level II", description: "Randomized controlled trial" },
  "randomized controlled trial": { level: "Level II", description: "Randomized controlled trial" },
  "cohort study": { level: "Level III", description: "Well-designed cohort study" },
  "case-control": { level: "Level III", description: "Well-designed case-control study" },
  "cross-sectional": { level: "Level IV", description: "Cross-sectional study" },
  "case series": { level: "Level IV", description: "Case series" },
  "case report": { level: "Level V", description: "Case report" },
  "expert opinion": { level: "Level V", description: "Expert opinion" },
  review: { level: "Level V", description: "Narrative review" },
};

export const meshMappingTool = tool(
  async ({ terms }) => {
    const results: Record<string, string[]> = {};

    for (const term of terms) {
      const normalizedTerm = term.toLowerCase().replace(/[^a-z0-9]/g, "_");

      // Check direct mappings
      if (MESH_MAPPINGS[normalizedTerm]) {
        results[term] = MESH_MAPPINGS[normalizedTerm];
      } else {
        // Try partial matching
        for (const [key, meshTerms] of Object.entries(MESH_MAPPINGS)) {
          if (
            key.includes(normalizedTerm) ||
            normalizedTerm.includes(key) ||
            term.toLowerCase().includes(key.replace(/_/g, " "))
          ) {
            results[term] = meshTerms;
            break;
          }
        }

        // If still no match, return original term as potential MeSH
        if (!results[term]) {
          results[term] = [term];
        }
      }
    }

    return JSON.stringify(results);
  },
  {
    name: "mesh_mapping",
    description:
      "Maps common medical terms to their corresponding MeSH (Medical Subject Headings) terms for PubMed search optimization",
    schema: z.object({
      terms: z.array(z.string()).describe("Array of medical terms to map to MeSH terms"),
    }),
  }
);

export const evidenceLevelTool = tool(
  async ({ publicationType, studyDesign }) => {
    const typeNormalized = publicationType.toLowerCase();
    const designNormalized = studyDesign?.toLowerCase() || "";

    // Check study design first (more specific)
    for (const [key, value] of Object.entries(EVIDENCE_LEVELS)) {
      if (designNormalized.includes(key) || typeNormalized.includes(key)) {
        return JSON.stringify(value);
      }
    }

    // Default to Level V if unknown
    return JSON.stringify({
      level: "Level V",
      description: "Unable to determine evidence level",
    });
  },
  {
    name: "evidence_level",
    description: "Classifies the evidence level (I-V) of a study based on its publication type and study design",
    schema: z.object({
      publicationType: z.string().describe("Publication type (e.g., 'Journal Article', 'Review')"),
      studyDesign: z.string().optional().describe("Study design if available (e.g., 'RCT', 'cohort study')"),
    }),
  }
);

export { MESH_MAPPINGS };
