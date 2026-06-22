"use client";

import { useState } from "react";
import { fetchPredict } from "@/lib/api";
import SkillTag from "@/components/SkillTag";

const COMMON_SKILLS = [
  "python",
  "aws",
  "docker",
  "sql",
  "spark",
  "kubernetes",
  "terraform",
  "airflow",
  "dbt",
  "kafka",
  "azure",
  "gcp",
  "pandas",
  "snowflake",
  "bigquery",
  "redshift",
  "react",
  "nodejs",
  "fastapi",
  "go",
  "rust",
  "java",
  "scala",
  "powerbi",
  "tableau",
];

function parseSkills(text) {
  return text
    .split(/[\s,]+/)
    .map((s) => s.trim().toLowerCase())
    .filter((s) => s.length > 0);
}

export default function PredictPage() {
  const [input, setInput] = useState("");
  const [skills, setSkills] = useState([]);
  const [prediction, setPrediction] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  function addSkillsFromInput() {
    const parsed = parseSkills(input);
    const merged = [...new Set([...skills, ...parsed])];
    setSkills(merged);
    setInput("");
  }

  function addSkill(skill) {
    const s = skill.toLowerCase();
    if (!skills.includes(s)) setSkills([...skills, s]);
  }

  function removeSkill(skill) {
    setSkills(skills.filter((s) => s !== skill));
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addSkillsFromInput();
    }
  }

  async function predict() {
    // Include any skills typed but not yet committed.
    const pending = parseSkills(input);
    const all = [...new Set([...skills, ...pending])];
    if (all.length === 0) {
      setError("Add at least one skill before predicting.");
      return;
    }
    setSkills(all);
    setInput("");
    setLoading(true);
    setError(null);
    setPrediction(null);

    const result = await fetchPredict(all);
    setLoading(false);

    if (!result) {
      setError(
        "Could not reach the prediction API. Make sure the FastAPI backend is running and the XGBoost model is loaded."
      );
      return;
    }

    setPrediction(result);
  }

  // Predicted salary + ±15% confidence interval.
  const predicted = prediction?.predicted_salary ?? prediction?.salary ?? prediction?.prediction;
  const lo = predicted != null ? predicted * 0.85 : null;
  const hi = predicted != null ? predicted * 1.15 : null;
  const fmt = (n) =>
    n != null
      ? `$${Math.round(Number(n)).toLocaleString("en-US")} MXN/mo`
      : null;

  return (
    <div className="space-y-8 max-w-3xl mx-auto">
      <header>
        <h1 className="text-3xl font-bold text-hirenovik-text">
          Salary Predictor
        </h1>
        <p className="text-hirenovik-text-secondary mt-2">
          Select your skills and the XGBoost model predicts a monthly salary
          (MXN) based on patterns learned from thousands of LATAM tech job
          listings. Results show a ±15% confidence interval.
        </p>
      </header>

      {/* Skills input */}
      <section className="bg-hirenovik-card rounded-lg p-6 border border-hirenovik-border space-y-4">
        <label className="block">
          <span className="text-sm text-hirenovik-text-secondary">
            Your skills
          </span>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type skills separated by commas or spaces (e.g. python, aws, docker) and press Enter…"
            rows={3}
            className="mt-2 w-full bg-hirenovik-bg text-hirenovik-text border border-hirenovik-border rounded-md p-3 text-sm focus:outline-none focus:border-hirenovik-link resize-y"
          />
        </label>

        {skills.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {skills.map((s) => (
              <SkillTag key={s} skill={s} onRemove={removeSkill} />
            ))}
          </div>
        )}

        {/* Quick-add chips */}
        <div>
          <p className="text-xs text-hirenovik-text-secondary mb-2">
            Common skills — click to add
          </p>
          <div className="flex flex-wrap gap-2">
            {COMMON_SKILLS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => addSkill(s)}
                disabled={skills.includes(s)}
                className="text-xs border border-hirenovik-border rounded-full px-2.5 py-1 text-hirenovik-text-secondary hover:text-hirenovik-text hover:border-hirenovik-link disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        <button
          type="button"
          onClick={predict}
          disabled={loading}
          className="w-full sm:w-auto bg-hirenovik-link hover:opacity-90 text-white rounded-md px-6 py-2.5 text-sm font-medium disabled:opacity-50 transition-opacity"
        >
          {loading ? "Predicting…" : "Predict salary"}
        </button>
      </section>

      {/* Result */}
      {error && (
        <div className="bg-red-900/20 border border-red-800 text-red-300 rounded-lg p-4 text-sm">
          {error}
        </div>
      )}

      {prediction && !error && (
        <section className="bg-hirenovik-card rounded-lg p-8 border border-hirenovik-border text-center">
          <p className="text-hirenovik-text-secondary text-sm">
            Predicted monthly salary
          </p>
          {predicted != null ? (
            <>
              <p className="text-4xl font-bold text-hirenovik-accent mt-2">
                {fmt(predicted)}
              </p>
              <p className="text-hirenovik-text-secondary mt-3 text-sm">
                Confidence interval (±15%):{" "}
                <span className="text-hirenovik-text">
                  {fmt(lo)} – {fmt(hi)}
                </span>
              </p>
            </>
          ) : (
            <p className="text-hirenovik-text mt-2">
              {JSON.stringify(prediction)}
            </p>
          )}
        </section>
      )}
    </div>
  );
}
