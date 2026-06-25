const analyzeButton = document.querySelector("#analyze-button");
const statusText = document.querySelector("#status");
const stageText = document.querySelector("#stage");
const gameStrengthText = document.querySelector("#game-strength");
const strategyText = document.querySelector("#strategy");
const explanationText = document.querySelector("#explanation");
const priorityText = document.querySelector("#priority");
const strategyScoreText = document.querySelector("#strategy-score");
const learningSignalBox = document.querySelector("#learning-signal");
const decisionLogText = document.querySelector("#decision-log");
const errorBox = document.querySelector("#error-box");
const feedbackUsefulButton = document.querySelector("#feedback-useful");
const feedbackNotUsefulButton = document.querySelector("#feedback-not-useful");
const feedbackStatusText = document.querySelector("#feedback-status");

let latestResult = null;

function renderStars(score) {
  const filledStars = Math.max(1, Math.min(5, Math.ceil(score / 20)));
  return "★".repeat(filledStars) + "☆".repeat(5 - filledStars);
}

function hideError() {
  errorBox.hidden = true;
  errorBox.textContent = "";
}

function renderResult(result) {
  latestResult = result;
  stageText.textContent = result.stage;
  gameStrengthText.textContent = result.game_strength;
  strategyText.textContent = result.strategy;
  priorityText.textContent = result.priority.join(" > ");
  const riskLevel = result.decision_log?.process?.product_insight?.risk_level || "medium";
  strategyScoreText.textContent = `${renderStars(result.strategy_score)} ${result.strategy_score} / 100`;
  strategyScoreText.classList.remove("risk-low", "risk-medium", "risk-high");
  strategyScoreText.classList.add(`risk-${riskLevel}`);
  explanationText.textContent = result.explanation;
  decisionLogText.textContent = JSON.stringify(result.decision_log, null, 2);

  const signal = result.learning_signal;
  learningSignalBox.classList.toggle("signal-danger", signal.should_adjust);
  learningSignalBox.classList.toggle("signal-success", !signal.should_adjust);
  learningSignalBox.classList.remove("signal-neutral");
  learningSignalBox.textContent = signal.adjustment_hint;
  feedbackUsefulButton.disabled = false;
  feedbackNotUsefulButton.disabled = false;
  feedbackStatusText.textContent = "可以提交本次推荐反馈";
}

function renderError(message) {
  errorBox.hidden = false;
  errorBox.textContent = message;
  statusText.textContent = "分析失败";
}

analyzeButton.addEventListener("click", async () => {
  analyzeButton.disabled = true;
  statusText.textContent = "正在识别对局并生成推荐...";
  hideError();

  try {
    const response = await window.jccApi.analyzeMockScreenshot();
    if (!response.success) {
      renderError(response.error || "未知错误");
      return;
    }

    renderResult(response.data);
    statusText.textContent = "对局分析完成";
  } catch (error) {
    renderError(error.message);
  } finally {
    analyzeButton.disabled = false;
  }
});

async function submitFeedback(userAction, result, comment) {
  if (!latestResult) {
    feedbackStatusText.textContent = "请先完成一次分析";
    return;
  }

  feedbackUsefulButton.disabled = true;
  feedbackNotUsefulButton.disabled = true;
  feedbackStatusText.textContent = "正在提交反馈...";

  const response = await window.jccApi.submitFeedback({
    strategy: latestResult.strategy,
    user_action: userAction,
    result,
    comment,
  });

  if (response.success) {
    feedbackStatusText.textContent = "反馈已记录";
  } else {
    feedbackStatusText.textContent = `反馈提交失败：${response.error || "未知错误"}`;
    feedbackUsefulButton.disabled = false;
    feedbackNotUsefulButton.disabled = false;
  }
}

feedbackUsefulButton.addEventListener("click", () => {
  submitFeedback("useful", "unknown", "用户认为推荐有用");
});

feedbackNotUsefulButton.addEventListener("click", () => {
  submitFeedback("not_useful", "unknown", "用户认为推荐没用");
});
