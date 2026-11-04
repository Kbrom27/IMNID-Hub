import {
  Sparkles,
  Layers,
  Wrench,
  Upload,
  Download,
  FolderOpen,
  Server,
  ArrowRight,
  FileSpreadsheet,
  FileText,
  Code,
} from 'lucide-react';

export const TOOLS_3X = [
  {
    id: 'cm01_bahmni',
    code: 'CM-01',
    name: 'Bahmni (CSV) to OpenMRS 3 (JSON) Converter',
    desc: 'Convert Bahmni CSV format concepts and concept sets into OpenMRS 3.x import-ready JSON files.',
    icon: FileSpreadsheet,
    endpoint: '/api/concepts/convert-bahmni',
  },
  {
    id: 'cm02_import',
    code: 'CM-02',
    name: 'Import Concepts & Sets (JSON) to OpenMRS 3.x',
    desc: 'Upload and batch import concepts and sets to an OpenMRS 3.x server via REST API with pre-flight check.',
    icon: Server,
    endpoint: '/api/concepts/import',
  },
  {
    id: 'cm03_export_set',
    code: 'CM-03',
    name: 'Export Concept Set (JSON) from OpenMRS 3.x',
    desc: 'Fetch a full concept set hierarchy from OpenMRS 3.x and export it as an import-ready JSON bundle.',
    icon: Download,
    endpoint: '/api/concepts/export-set',
  },
  {
    id: 'cm04_dhis2_conv',
    code: 'CM-04',
    name: 'DHIS2 Tracker Metadata to OpenMRS 3 Concept Converter',
    desc: 'Convert DHIS2 Tracker metadata JSON or Data Dictionary Excel files into staged concept folders.',
    icon: FolderOpen,
    endpoint: '/api/concepts/convert-dhis2',
  },
  {
    id: 'cm05_bulk_import',
    code: 'CM-05',
    name: 'Bulk Folder Concept Importer to OpenMRS 3.x',
    desc: 'Recursively scan and bulk import all concepts and sets across program stages and sections.',
    icon: Layers,
    endpoint: '/api/concepts/bulk-import',
  },
  {
    id: 'cm06_gen_schemas',
    code: 'CM-06',
    name: 'DHIS2 to OpenMRS 3 Form Schema Generator',
    desc: 'Build OpenMRS 3.x form schemas automatically from DHIS2 metadata and concept mapping dictionaries.',
    icon: FileText,
    endpoint: '/api/concepts/generate-schemas',
  },
  {
    id: 'cm07_export_all',
    code: 'CM-07',
    name: 'Export All Concepts (CSV/JSON) from OpenMRS 3.x',
    desc: 'Export the complete concept dictionary from an OpenMRS 3.x instance to CSV or JSON format.',
    icon: Download,
    endpoint: '/api/concepts/export-all',
  },
  {
    id: 'cm08_enhanced_gen',
    code: 'CM-08',
    name: 'Enhanced Form Schema Generator with Logic & Rules',
    desc: 'Generate 3.x form schemas with translated program rules, skip logic, and validation formulas.',
    icon: Sparkles,
    endpoint: '/api/concepts/enhanced-generator',
  },

  {
    id: 'cm09_export_form_concepts',
    code: 'CM-09',
    name: 'Export Form Concepts (JSON) from OpenMRS 3.x',
    desc: 'Extract all concept UUIDs referenced in form schemas and download full definitions from the server.',
    icon: ArrowRight,
    endpoint: '/api/concepts/export-form-concepts',
  },
  {
    id: 'cm10_import_schemas',
    code: 'CM-10',
    name: 'Import Form Schemas (JSON) to OpenMRS 3.x',
    desc: 'Validate and import all JSON form schemas in a directory into OpenMRS 3.x form engine.',
    icon: Upload,
    endpoint: '/api/concepts/import-schemas',
  },
];

export const TOOLS_21 = [
  {
    id: 'cm11_legacy_export',
    code: 'CM-11',
    name: 'Legacy 2.1 Concept Exporter',
    desc: 'Export concepts and form mappings from OpenMRS 2.1 legacy servers via standard REST API with auth.',
    icon: Download,
    endpoint: '/api/concepts/legacy-export',
  },
  {
    id: 'cm12_legacy_conv',
    code: 'CM-12',
    name: 'Legacy 2.1 DHIS2 Concept Converter',
    desc: 'Convert DHIS2 mapping spreadsheet into OpenMRS 2.1 format concepts.csv and concept_sets.csv organized by stage and section.',
    icon: FileSpreadsheet,
    endpoint: '/api/concepts/legacy-convert',
  },
];

export const DEFAULT_BLANK_SCHEMA = {
  name: 'Clinical Assessment Form',
  version: '1.0.0',
  published: true,
  retired: false,
  uuid: 'f0000000-0000-0000-0000-000000000001',
  description: 'Standard clinical observation and assessment form schema.',
  encounterType: 'e22e39fd-7db2-45e7-80f1-60fa0d7a4378',
  processor: 'EncounterFormProcessor',
  pages: [
    {
      label: 'Initial Triage',
      sections: [
        {
          label: 'Vital Signs',
          isExpanded: 'true',
          questions: [
            {
              id: 'systolicBP',
              label: 'Systolic Blood Pressure (mmHg)',
              type: 'obs',
              required: 'true',
              questionOptions: {
                concept: '5085AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
                rendering: 'number',
              },
              validators: [
                {
                  failsWhenExpression: 'systolicBP > 250 || systolicBP < 40',
                  message: 'Systolic BP value out of normal clinical range (40 - 250 mmHg)',
                },
              ],
            },
            {
              id: 'temperature',
              label: 'Body Temperature (°C)',
              type: 'obs',
              required: 'false',
              questionOptions: {
                concept: '5088AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
                rendering: 'number',
              },
            },
            {
              id: 'generalCondition',
              label: 'General Patient Condition',
              type: 'obs',
              required: 'false',
              questionOptions: {
                concept: '160000AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
                rendering: 'radio',
                answers: [
                  { concept: '159405AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA', label: 'Good' },
                  { concept: '159406AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA', label: 'Fair' },
                  { concept: '159407AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA', label: 'Critical' },
                ],
              },
            },
            {
              id: 'criticalNotes',
              label: 'Critical Condition Clinical Notes',
              type: 'obs',
              required: 'true',
              hide: {
                hideWhenExpression: 'generalCondition !== "159407AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"',
              },
              questionOptions: {
                concept: '160001AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
                rendering: 'text',
              },
            },
          ],
        },
      ],
    },
  ],
};
