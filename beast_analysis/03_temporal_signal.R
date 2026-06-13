#!/usr/bin/env Rscript
# Step 3: 时间信号检验 — root-to-tip 回归
library(ape)
library(phytools)

DIR <- "F:/水生无脊椎动物数据库/beast_analysis"

# 读 IQ-TREE 输出的 ML 树
tree <- read.tree(file.path(DIR, "iqtree.treefile"))
metadata <- read.delim(file.path(DIR, "metadata.tsv"), stringsAsFactors = FALSE)

# 确保 tip labels 匹配
cat("Tree tips:", length(tree$tip.label), "\n")
cat("Metadata rows:", nrow(metadata), "\n")

# 匹配日期
tip_dates <- metadata$dec_year[match(tree$tip.label, metadata$tip_label)]
if (any(is.na(tip_dates))) {
  cat("WARNING: Some tips have no date match!\n")
  print(tree$tip.label[is.na(tip_dates)])
  # drop tips without dates
  keep <- !is.na(tip_dates)
  tree <- keep.tip(tree, tree$tip.label[keep])
  tip_dates <- tip_dates[keep]
}

# 中点生根
tree_rooted <- midpoint.root(tree)

# 计算 root-to-tip 遗传距离
root_to_tip <- diag(vcv(tree_rooted))

# 线性回归
fit <- lm(root_to_tip ~ tip_dates)
r2  <- summary(fit)$r.squared
p   <- summary(fit)$coefficients[2, 4]
rate <- coef(fit)[2]  # 替换/位点/年

cat(sprintf("\n=== Temporal Signal Results ===\n"))
cat(sprintf("R² = %.4f\n", r2))
cat(sprintf("p-value = %.4g\n", p))
cat(sprintf("Evolutionary rate = %.2e substitutions/site/year\n", rate))
cat(sprintf("Root age estimate = %.1f\n", -coef(fit)[1] / rate))

if (r2 > 0.05 && rate > 0) {
  cat("\n✓ Temporal signal DETECTED — proceed with BEAST tip-dating\n")
} else {
  cat("\n✗ WEAK or NO temporal signal — tip-dating may be unreliable\n")
  cat("  Consider: (1) more sequences, (2) longer date span, (3) BETS formal test\n")
}

# === 出图 ===
pdf(file.path(DIR, "temporal_signal.pdf"), width = 7, height = 6)

# 主图
plot(tip_dates, root_to_tip,
     xlab = "Sampling date (decimal year)",
     ylab = "Root-to-tip genetic distance",
     main = "Dicistroviridae RdRp — Temporal Signal",
     pch = 21, bg = "#4472C4", cex = 1.5, col = "#2F5496")
abline(fit, col = "#C00000", lwd = 2.5, lty = 2)

# 标注统计量
txt <- sprintf("R² = %.3f\np = %.2e\nrate = %.2e subs/site/yr",
               r2, p, rate)
legend("topleft", legend = txt, bty = "n", cex = 0.9,
       text.col = "#333333")

# 残差图
par(mfrow = c(1, 2))
plot(fit, which = 1, main = "Residuals vs Fitted")
plot(fit, which = 2, main = "Normal Q-Q")

dev.off()
cat(sprintf("\nPlot saved: %s\n", file.path(DIR, "temporal_signal.pdf")))
