export function shapToHumanText(shapValue: number, featureName: string, featureLabels: Record<string, string>): {
  label: string;
  impact: "large" | "medium" | "small";
  direction: "up" | "down";
  text: string;
  icon: string;
} {
  const absVal = Math.abs(shapValue);
  const impact = absVal >= 0.05 ? "large" : absVal >= 0.02 ? "medium" : "small";
  const direction = shapValue > 0 ? "up" : "down";
  const label = featureLabels[featureName] || featureName;

  const impactText = impact === "large" ? "大きく" : impact === "medium" ? "やや" : "わずかに";
  const dirText = direction === "up" ? "リスクを上昇" : "リスクを低減";
  const icon = direction === "up" ? "⬆" : "⬇";

  return {
    label,
    impact,
    direction,
    text: `${impactText}${dirText}させています`,
    icon,
  };
}

export function aucToStars(auc: number): { stars: number; label: string } {
  if (auc >= 0.95) return { stars: 5, label: "非常に高い" };
  if (auc >= 0.90) return { stars: 4, label: "高い" };
  if (auc >= 0.85) return { stars: 3, label: "中程度" };
  if (auc >= 0.80) return { stars: 2, label: "やや低い" };
  return { stars: 1, label: "低い" };
}

export function renderStars(count: number): string {
  return "★".repeat(count) + "☆".repeat(5 - count);
}

export function riskScoreToText(score: number): string {
  const pct = Math.round(score * 100);
  if (pct >= 70) return "非常に高い離職リスク";
  if (pct >= 50) return "高い離職リスク";
  if (pct >= 30) return "中程度のリスク";
  if (pct >= 15) return "低めのリスク";
  return "安定";
}
