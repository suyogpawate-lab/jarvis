# JARVIS adapter optimization and accuracy retention

## Data collection

Use /learn prefer only when the owner explicitly supplies a prompt, preferred answer and rejected answer. No conversation is silently captured. Keep private, identifying or credential-bearing examples out of the dataset. Review and redact the local JSONL before export.

## Recommended training sequence

1. Freeze and checksum the current baseline model and its inference configuration.
2. Build a versioned evaluation set that is separate from training and preference data. Include representative task execution, coding, reasoning, screen interpretation, instruction following and safety cases.
3. Establish baseline metrics before training. Use identical prompts, decoding settings and scoring criteria for every candidate.
4. Optionally run supervised LoRA fine-tuning on reviewed, high-quality demonstrations. Use a small learning rate, conservative epochs and rank; avoid training on noisy preference pairs as if they were ground-truth answers.
5. Run DPO using reviewed chosen/rejected pairs and a frozen reference policy. Prefer conservative beta and early stopping; do not assume lower training loss means better task accuracy.
6. Evaluate the candidate on the untouched held-out set. Record task_accuracy, instruction_following and safety_pass_rate as values from 0 to 1.
7. Compare baseline and candidate using intelligence.model_evaluation.ModelEvaluation. Reject any candidate exceeding the configured regression budget. Keep the baseline as the active model unless a human explicitly promotes the candidate.
8. Run a separate regression suite on real JARVIS workflows before deployment; monitor latency, memory, tool-call correctness and failure rates after deployment.

## Accuracy is not one scalar

Track per-domain metrics and critical failure counts as well as aggregate scores. A candidate must not hide a severe regression in coding, screen perception or safety behind improvements in another category. Maintain a frozen golden set, a fresh challenge set and an adversarial safety set. Avoid overlap between training examples and evaluation examples.

## LoRA vs RLHF

LoRA is a parameter-efficient adaptation method. DPO is preference optimization using chosen/rejected examples and a reference policy; it is often grouped under RLHF-style alignment but does not train a separate reward model. Classical RLHF additionally needs reward-model training and a controlled policy-optimization stage. Neither the training nor reward-model pipeline runs on the low-memory Android tablet.

## Deployment policy

Never overwrite the baseline model. Store candidate adapters in versioned directories off-device, validate hashes and compatibility, then promote explicitly. Provide immediate rollback to the frozen baseline. Groq remains the reasoning provider unless a separately evaluated local model is deliberately configured.
