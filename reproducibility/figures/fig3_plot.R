# Fig 3. Evidence system and data quality of AquaVir-KB (iMetaOmics) -- R build.
# Figure contract: one evidence corpus described end to end -- what it is made of (A), how well
# the isolates/proteins are covered (B), how the raw corpus was curated into it (C), and how
# confidently hosts are linked (D). Four panels, no empty cells.
# Style: white minimalist lollipop + 100% stacked vertical columns.
# Numbers verbatim from TRUTH_TABLE_FIGURES_20261005.md sec.4 (2026-10-05 read-only re-measure).
suppressPackageStartupMessages({
  library(ggplot2); library(patchwork); library(scales); library(svglite); library(ragg); library(grid)
})

OUT <- "D:/桌面/AquaVir_Figures_20261005/Fig3"   # canonical submission figure dir

# ---- canonical numbers read from the stats file (do not hardcode) ------------
# Regenerate fig_stats.tsv with: build_fig_numbers.py (frozen snapshot, read-only).
STATS <- "D:/桌面/AquaVir_Figures_20261005/src/fig_stats.tsv"
N <- local({
  d <- read.delim(STATS, stringsAsFactors = FALSE)
  setNames(as.numeric(d$value), d$key)
})

INK <- "#1a1a1a"
GREY_D <- "#8b96a3"
CUR_COLS <- c("#9aa7b4", "#d6604d", "#4393c3", "#f2b56b")                 # curation: neutral/reject/manual/await
REJ_COLS <- c("#b2182b", "#d6604d", "#ef8a62", "#f4a582", "#fddbc7")      # rejections: dark -> light red
STR_COLS <- c("#9ecae1", "#08519c")                                       # medium / high
RAMP_A <- c("#c6dbef", "#08519c")   # Blues
RAMP_D <- c("#dadaeb", "#54278f")   # Purples
RAMP_E <- c("#ccece6", "#006d2c")   # BuGn  (isolate metadata)
RAMP_F <- c("#c7e9c0", "#00441b")   # Greens (protein annotation)

base_theme <- theme_classic(base_size = 6.5, base_family = "Arial") +
  theme(
    axis.line.x = element_line(linewidth = 0.35, colour = "black"),
    axis.line.y = element_blank(),
    axis.ticks.x = element_line(linewidth = 0.35, colour = "black"),
    axis.ticks.y = element_blank(),
    axis.title = element_text(size = 6.5),
    axis.text = element_text(size = 6, colour = "black"),
    plot.title = element_text(size = 7, face = "bold", hjust = 0, margin = margin(b = 3)),
    legend.title = element_blank(),
    legend.text = element_text(size = 5.6),
    legend.key.size = unit(0.24, "cm"),
    legend.margin = margin(0, 0, 0, 0),
    legend.spacing.y = unit(0.015, "cm"),
    plot.margin = margin(3, 4, 3, 4),
    panel.grid = element_blank()
  )
theme_set(base_theme)

# ---- data (TRUTH_TABLE_FIGURES_20261005.md sec.4) ---------------------------
TYPES <- data.frame(
  lab = c("Diagnosis", "Pathogenicity", "Host range", "Temperature", "Other", "Mortality",
          "Transmission", "Outbreak", "Natural infection", "Virulence"),
  v   = c(41864, 19683, 16327, 8466, 5836, 589, 202, 111, 72, 18))          # sum 93,168
STRENGTH <- data.frame(lab = c("Medium", "High"), v = c(75170, 17998))      # sum 93,168
CURATION <- data.frame(
  lab = c("Auto-imported", "Rejected", "Manually checked", "Awaiting review"),
  v   = c(145705, 106594, 93180, 7681))                                     # sum 353,160
REJECTED <- data.frame(
  lab = c("Non-viral", "Non-target", "Duplicate", "Off-topic", "Other"),
  v   = c(N[["REJPCT_NONVIRAL"]], N[["REJPCT_NONTARGET"]], N[["REJPCT_DUPLICATE"]],
          N[["REJPCT_OFFTOPIC"]], N[["REJPCT_OTHER"]]))                       # % from fig_stats.tsv
TIERS <- data.frame(
  lab = c("Candidate / context", "Disease-associated", "Confirmed infection",
          "Excluded host", "Awaiting reference"),
  v   = c(1764, 1749, 736, 701, 6))                                         # sum 4,956
COMPLETE <- data.frame(
  lab = c("Reference", "Genome type", "Country", "Collection year", "Host",
          "Coordinates", "Isolation source"),
  v   = c(95.9, 85.5, 69.0, 65.6, 43.1, 42.5, 30.1))                        # denom 5,403
ANNOT <- data.frame(
  lab = c("InterPro domain", "GO term", "UniProt link"),
  v   = c(88.5, 78.0, 39.1))                                                # denom 29,004

lum <- function(hex) {
  r <- strtoi(substr(hex, 2, 3), 16) / 255
  g <- strtoi(substr(hex, 4, 5), 16) / 255
  b <- strtoi(substr(hex, 6, 7), 16) / 255
  0.299 * r + 0.587 * g + 0.114 * b
}

# ---- lollipop (rank-graded single-hue ramp) ---------------------------------
lollipop <- function(d, ramp, title, xlabel, pct = FALSE) {
  dd <- d[order(d$v), , drop = FALSE]              # ascending -> largest on top
  dd$lab <- factor(dd$lab, levels = dd$lab)
  dd$col <- grDevices::colorRampPalette(ramp)(nrow(dd))
  mx <- max(dd$v)
  if (pct) {
    lim <- c(0, 112); brk <- c(0, 25, 50, 75, 100)
    lb <- c("0", "25", "50", "75", "100%"); fmt <- function(v) sprintf("%.1f%%", v)
  } else {
    lim <- c(0, mx * 1.35)
    brk <- unique(c(0, signif(mx / 2, 1), signif(mx, 1)))     # 3 evenly-nice breaks
    lb <- formatC(brk, big.mark = ",", format = "d")
    fmt <- function(v) formatC(v, big.mark = ",", format = "d")
  }
  ggplot(dd, aes(y = lab)) +
    geom_segment(aes(x = 0, xend = v, yend = lab, colour = col),
                 linewidth = 0.55, lineend = "round") +
    geom_point(aes(x = v, colour = col), size = 1.35) +
    geom_text(aes(x = v, y = lab, label = fmt(v)), hjust = -0.20, size = 1.85, colour = INK) +
    scale_colour_identity(guide = "none") +
    scale_x_continuous(limits = lim, breaks = brk, labels = lb,
                       expand = expansion(mult = c(0.04, 0.01))) +
    labs(title = title, x = xlabel, y = NULL) +
    theme(axis.text.x = element_text(size = 5.6))
}

# ---- 100% stacked vertical columns ------------------------------------------
mk_stack <- function(xv, cats, vals, cols, minlab) {
  pct <- vals / sum(vals) * 100
  ymax <- cumsum(pct); ymin <- c(0, head(ymax, -1))
  data.frame(x = xv, cat = cats, col = cols, ymin = ymin, ymax = ymax,
             mid = (ymin + ymax) / 2, pct = pct,
             lab = ifelse(pct >= minlab, sprintf("%.1f%%", pct), ""),
             tcol = ifelse(lum(cols) < 0.62, "white", INK),
             stringsAsFactors = FALSE)
}

rects <- function(df) {
  geom_rect(data = df, aes(xmin = x - w / 2, xmax = x + w / 2, ymin = ymin, ymax = ymax, fill = cat),
            colour = "white", linewidth = 0.4)
}

# A - evidence type (lollipop) -------------------------------------------------
pA <- lollipop(TYPES, RAMP_A, "A  Evidence type", "Evidence records")

# B - isolate metadata + protein annotation coverage (faceted % lollipop) -------
meta <- rbind(
  data.frame(lab = COMPLETE$lab, v = COMPLETE$v, grp = "Isolates (n = 5,403)"),
  data.frame(lab = ANNOT$lab,    v = ANNOT$v,    grp = "Proteins (n = 29,004)"))
GRPS <- c("Isolates (n = 5,403)", "Proteins (n = 29,004)")
meta$grp <- factor(meta$grp, levels = GRPS)
lv <- c(COMPLETE$lab[order(COMPLETE$v)], ANNOT$lab[order(ANNOT$v)])   # bottom -> top, per facet
meta$lab <- factor(meta$lab, levels = lv)
ce <- grDevices::colorRampPalette(RAMP_E)(nrow(COMPLETE)); names(ce) <- COMPLETE$lab[order(COMPLETE$v)]
cf <- grDevices::colorRampPalette(RAMP_F)(nrow(ANNOT));    names(cf) <- ANNOT$lab[order(ANNOT$v)]
meta$col <- c(ce, cf)[as.character(meta$lab)]

pB <- ggplot(meta, aes(y = lab)) +
  geom_segment(aes(x = 0, xend = v, yend = lab, colour = col), linewidth = 0.55, lineend = "round") +
  geom_point(aes(x = v, colour = col), size = 1.35) +
  geom_text(aes(x = v, label = sprintf("%.1f%%", v)), hjust = -0.20, size = 1.85, colour = INK) +
  scale_colour_identity(guide = "none") +
  scale_x_continuous(limits = c(0, 100), breaks = c(0, 25, 50, 75, 100),
                     labels = c("0", "25", "50", "75", "100%"),
                     expand = expansion(mult = c(0, 0.13))) +
  facet_grid(grp ~ ., scales = "free_y", space = "free_y") +
  labs(title = "B  Coverage", x = "Records with value (%)", y = NULL) +
  theme(axis.text.x = element_text(size = 5.6),
        strip.background = element_blank(),
        strip.text.y = element_text(size = 5.8, face = "bold", angle = 270, colour = GREY_D),
        panel.spacing.y = unit(3, "pt"))

# C - corpus composition: strength | curation | rejection reasons (3 columns) ---
s1 <- mk_stack(0, STRENGTH$lab, STRENGTH$v, STR_COLS, 8);  s1$w <- 0.72
s1$lab <- sprintf("%s\n%.1f%%", s1$cat, s1$pct)            # strength named inline
s2 <- mk_stack(1, CURATION$lab, CURATION$v, CUR_COLS, 9);  s2$w <- 0.72
s3 <- mk_stack(2, REJECTED$lab, REJECTED$v, REJ_COLS, 9);  s3$w <- 0.72
cc <- rbind(s1, s2, s3)
lev_c <- c(STRENGTH$lab, CURATION$lab, REJECTED$lab)
cc$cat <- factor(cc$cat, levels = lev_c)
cols_c <- setNames(c(STR_COLS, CUR_COLS, REJ_COLS), lev_c)
pC <- ggplot() + rects(cc) +
  geom_text(data = cc, aes(x = x, y = mid, label = lab, colour = tcol),
            size = 1.8, fontface = "bold", lineheight = 0.95) +
  scale_fill_manual(values = cols_c, breaks = c(CURATION$lab, REJECTED$lab)) +   # legend = 9
  scale_colour_identity(guide = "none") +
  scale_x_continuous(limits = c(-0.55, 2.55), breaks = c(0, 1, 2),
                     labels = c("Analysis set\n93,168", "All records\n353,160", "Rejected\n106,594"),
                     expand = expansion(mult = c(0, 0))) +
  scale_y_continuous(limits = c(0, 100), breaks = c(0, 25, 50, 75, 100),
                     labels = c("0", "25", "50", "75", "100%"),
                     expand = expansion(mult = c(0, 0))) +
  labs(title = "C  Corpus composition", x = NULL, y = NULL) +
  theme(axis.ticks.x = element_blank()) +
  guides(fill = guide_legend(nrow = 2, byrow = TRUE))

# D - host association tier (lollipop) ----------------------------------------
pD <- lollipop(TIERS, RAMP_D, "D  Host association tier", "Assessments")

# ---- assemble: 3 columns x 4 rows; A and B full height, C over D -------------
fig <- wrap_plots(pA, pB, pC, pD) +
  plot_layout(design = "ABC\nABC\nABD\nABD",
              widths = c(1.0, 1.0, 0.82), heights = c(1, 1, 1, 1),
              guides = "collect") +
  plot_annotation(
    title = "Fig. 3  Evidence system and data quality of AquaVir-KB",
    caption = paste0(
      "A, 93,168 manually checked evidence records by type. B, coverage of the 5,403 strict target isolates (metadata) and 29,004 proteins (annotation);\n",
      "KEGG pathways (0.04%) and structures (0.08%) are off-scale. C, corpus composition, left to right: the analysis set by evidence strength label, all\n",
      "353,160 raw records by curation outcome, and the 106,594 rejected records by reason (segments below 9% unlabelled:\n",
      "off-topic 1.95%, other 0.11%). D, 4,956 graded host-virus associations."),
    theme = theme(
      plot.title = element_text(size = 10.5, face = "bold", hjust = 0, family = "Arial"),
      plot.caption = element_text(size = 6.2, hjust = 0, colour = "#444444", family = "Arial",
                                  margin = margin(t = 6), lineheight = 1.5),
      legend.position = "bottom"))

W <- 7.4; H <- 4.9
svglite(file.path(OUT, "Fig3_evidence_quality_R.svg"), width = W, height = H)
print(fig); dev.off()
cairo_pdf(file.path(OUT, "Fig3_evidence_quality_R.pdf"), width = W, height = H, family = "Arial")
print(fig); dev.off()
agg_tiff(file.path(OUT, "Fig3_evidence_quality_R.tiff"), width = W, height = H, units = "in", res = 600)
print(fig); dev.off()
agg_png(file.path(OUT, "Fig3_evidence_quality_R.png"), width = W, height = H, units = "in", res = 300)
print(fig); dev.off()
cat("saved R figure 3 (4-panel)\n")
