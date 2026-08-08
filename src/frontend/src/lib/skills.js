const SKILL_ALIASES = {
  "node": "nodejs",
  "node js": "nodejs",
  "node.js": "nodejs",
  "postgres": "postgresql",
  "amazon web services": "aws",
  "google cloud": "gcp",
  "google cloud platform": "gcp",
  "c sharp": "csharp",
  "c#": "csharp",
  "c-sharp": "csharp",
  "js": "javascript",
  "java script": "javascript",
  "powerbi": "power_bi",
  "power bi": "power_bi",
  "power-bi": "power_bi",
  "scikit learn": "scikit_learn",
  "scikit-learn": "scikit_learn",
  "sklearn": "scikit_learn",
  "machinelearning": "machine_learning",
  "machine-learning": "machine_learning",
  "deeplearning": "deep_learning",
  "deep-learning": "deep_learning",
};

const SKILL_LABELS = {
  "python": "Python",
  "javascript": "JavaScript",
  "typescript": "TypeScript",
  "nodejs": "Node.js",
  "react": "React",
  "nextjs": "Next.js",
  "postgresql": "PostgreSQL",
  "mysql": "MySQL",
  "mongodb": "MongoDB",
  "aws": "AWS",
  "azure": "Azure",
  "gcp": "Google Cloud",
  "docker": "Docker",
  "kubernetes": "Kubernetes",
  "git": "Git",
  "github": "GitHub",
  "power_bi": "Power BI",
  "tableau": "Tableau",
  "apache_spark": "Apache Spark",
  "spark": "Apache Spark",
  "kafka": "Apache Kafka",
  "apache_kafka": "Apache Kafka",
  "airflow": "Apache Airflow",
  "apache_airflow": "Apache Airflow",
  "terraform": "Terraform",
  "snowflake": "Snowflake",
  "scikit_learn": "scikit-learn",
  "pytorch": "PyTorch",
  "tensorflow": "TensorFlow",
  "csharp": "C#",
  "java": "Java",
  "go": "Go",
  "rust": "Rust",
  "ruby": "Ruby",
  "php": "PHP",
  "swift": "Swift",
  "kotlin": "Kotlin",
  "scala": "Scala",
  "r": "R",
  // Acronym-based skills that need explicit casing
  "sql": "SQL",
  "ci_cd": "CI/CD",
  "rest_api": "REST API",
  "sql_server": "SQL Server",
  "html_css": "HTML/CSS",
  "nosql": "NoSQL",
  "etl": "ETL",
  "iot": "IoT",
  "erp": "ERP",
  "llm": "LLM",
  "grc": "GRC",
  "hvac": "HVAC",
  "css": "CSS",
  "dotnet": ".NET",
  "dynamodb": "DynamoDB",
  "bigquery": "BigQuery",
  "sap": "SAP",
};

const ICON_MAP = {
  "python": "siPython",
  "javascript": "siJavascript",
  "typescript": "siTypescript",
  "nodejs": "siNodedotjs",
  "react": "siReact",
  "nextjs": "siNextdotjs",
  "postgresql": "siPostgresql",
  "mysql": "siMysql",
  "mongodb": "siMongodb",
  "aws": "siAmazonwebservices",
  "gcp": "siGooglecloud",
  "docker": "siDocker",
  "kubernetes": "siKubernetes",
  "git": "siGit",
  "github": "siGithub",
  "apache_spark": "siApachespark",
  "spark": "siApachespark",
  "kafka": "siApachekafka",
  "apache_kafka": "siApachekafka",
  "airflow": "siApacheairflow",
  "apache_airflow": "siApacheairflow",
  "terraform": "siTerraform",
  "snowflake": "siSnowflake",
  "scikit_learn": "siScikitlearn",
  "pytorch": "siPytorch",
  "tensorflow": "siTensorflow",
  "java": "siOpenjdk",
  "go": "siGo",
  "rust": "siRust",
  "ruby": "siRuby",
  "php": "siPhp",
  "swift": "siSwift",
  "kotlin": "siKotlin",
  "scala": "siScala",
  "r": "siR",
};

export function normalizeSkill(raw) {
  const key = (raw || "").trim().toLowerCase().replace(/\s+/g, " ");
  return SKILL_ALIASES[key] || key;
}

export function skillLabel(canonical) {
  if (SKILL_LABELS[canonical]) return SKILL_LABELS[canonical];
  return canonical
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function getSkillIcon(canonical) {
  return ICON_MAP[canonical] || null;
}

export function formatSkillLabel(raw) {
  return skillLabel(normalizeSkill(raw));
}
