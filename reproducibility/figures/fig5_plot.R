# Fig 5. Analysis and visualization tools of AquaVir-KB -- R build (ggplot2 + patchwork + ggtree).
# Figure contract: the database is not just a catalogue -- it supports analysis. Five panels:
# (A) RdRp-based family assignment (1,213 sequences) plus a representative family phylogeny;
# (B) host-virus association network (confirmed-infection + disease-associated tiers);
# (C) a representative predicted protein structure (WSSV VP28) coloured by model confidence;
# (D) the aggregated WSSV evidence graph (3,062 manually checked records, the analysis set);
# (E) the BLAST suite and its curated sequence snapshot.
# Numbers come from src/fig_stats.tsv and the read-only pull in src/fig5_data/ (do not hardcode).
suppressPackageStartupMessages({
  library(ggplot2); library(patchwork); library(scales); library(svglite); library(ragg)
  library(grid); library(jsonlite); library(ape); library(ggtree); library(tidyr); library(dplyr)
})

BASE  <- "D:/桌面/AquaVir_Figures_20261005"
OUT   <- file.path(BASE, "Fig5")
DAT   <- file.path(BASE, "src", "fig5_data")
STATS <- file.path(BASE, "src", "fig_stats.tsv")

N <- local({ d <- read.delim(STATS, stringsAsFactors = FALSE); setNames(as.numeric(d$value), d$key) })
`%||%` <- function(a, b) if (is.null(a)) b else a

INK <- "#1a1a1a"; GREY <- "#5b6470"
SET <- theme_classic(base_size = 6.5, base_family = "Arial") +
  theme(axis.line = element_line(linewidth = 0.35, colour = "black"),
        axis.ticks = element_line(linewidth = 0.35, colour = "black"),
        axis.title = element_text(size = 6.4), axis.text = element_text(size = 5.8, colour = INK),
        plot.title = element_text(size = 7.2, face = "bold", hjust = 0, margin = margin(b = 3)),
        legend.title = element_blank(), legend.text = element_text(size = 5.4),
        legend.key.size = unit(0.22, "cm"), legend.margin = margin(0, 0, 0, 0),
        plot.margin = margin(3, 5, 3, 3), panel.grid = element_blank())
theme_set(SET)

CONF_COLS <- c(high = "#08519c", medium = "#6baed6", low = "#c6dbef")

# =============================== Panel A =====================================
# A1: family assignment (top 12 families), stacked by confidence
fam <- fromJSON(file.path(DAT, "rdrp_families.json"))
fam$family <- factor(fam$family, levels = rev(fam$family[order(fam$total)]))
famL <- tidyr::pivot_longer(fam, c("high", "medium", "low"), names_to = "conf", values_to = "n")
famL$conf <- factor(famL$conf, levels = c("low", "medium", "high"))
fam$lab <- ifelse(fam$total >= 90, as.character(fam$total), "")
pA1 <- ggplot(famL, aes(x = n, y = family, fill = conf)) +
  geom_col(width = 0.72) +
  geom_text(data = fam, aes(x = total, y = family, label = lab), inherit.aes = FALSE,
            hjust = -0.18, size = 1.9, colour = INK) +
  scale_fill_manual(values = CONF_COLS, breaks = c("high", "medium", "low"),
                    labels = c("high", "medium", "low confidence")) +
  scale_x_continuous(limits = c(0, max(fam$total) * 1.16), expand = expansion(mult = c(0, 0))) +
  labs(title = "A  RdRp-based family assignment", x = "Sequences (of 1,213)", y = NULL) +
  theme(legend.position = c(0.80, 0.76), legend.background = element_rect(fill = "white", colour = NA))

# A2: representative family phylogeny (crustacean Marnaviridae-like RdRp, IQ-TREE)
tr <- read.tree(file.path(DAT, "marnaviridae_rdrp_iqtree.contree"))
meta <- do.call(rbind, lapply(tr$tip.label, function(t) {
  p <- strsplit(t, "\\|")[[1]]
  data.frame(accession = p[1], name = gsub("_", " ", p[2]), host = gsub("_", " ", p[3]),
             stringsAsFactors = FALSE)
}))
tr$tip.label <- meta$accession
trd <- data.frame(label = meta$accession, lab = paste0(meta$name, "\n", meta$host),
                  host = meta$host, stringsAsFactors = FALSE)
pA2 <- ggtree(tr, size = 0.32, colour = INK) %<+% trd +
  geom_tiplab(aes(label = lab), size = 1.55, colour = GREY,
              linesize = 0.24, align = TRUE, offset = 0.02, lineheight = 0.86) +
  geom_tippoint(aes(colour = host), size = 0.9) +
  scale_colour_manual(values = c("Litopenaeus vannamei" = "#2166ac", "Marsupenaeus japonicus" = "#b2182b")) +
  labs(title = "     Representative RdRp phylogeny (Marnaviridae-like)") +
  theme_tree2() +
  theme(plot.title = element_text(size = 6.6, face = "bold", hjust = 0, margin = margin(b = 2)),
        legend.position = c(0.30, 0.14), legend.text = element_text(size = 4.8),
        legend.background = element_rect(fill = "white", colour = NA),
        plot.margin = margin(3, 2, 3, 2))
pA <- pA1 | pA2

# =============================== Panel B =====================================
net <- fromJSON(file.path(DAT, "network_tier.json"))$rows
agg <- net %>% group_by(virus, host) %>% summarise(n = sum(n), .groups = "drop")
vt <- agg %>% group_by(virus) %>% summarise(t = sum(n), .groups = "drop") %>% arrange(desc(t))
ht <- agg %>% group_by(host)  %>% summarise(t = sum(n), .groups = "drop") %>% arrange(desc(t))
NV <- 10; NH <- 14
Vv <- head(vt, NV); Hh <- head(ht, NH)
agg2 <- agg %>% filter(virus %in% Vv$virus, host %in% Hh$host)
Vv$y <- seq(1, 0, length.out = nrow(Vv)); Hh$y <- seq(1, 0, length.out = nrow(Hh))
agg2 <- agg2 %>% left_join(Vv %>% select(virus, yv = y), by = "virus") %>%
  left_join(Hh %>% select(host, yh = y), by = "host")
shorten <- function(s, n = 22) ifelse(nchar(s) > n, paste0(substr(s, 1, n - 1), "\u2026"), s)
pB <- ggplot() +
  geom_segment(data = agg2, aes(x = 0.02, xend = 0.98, y = yv, yend = yh),
               colour = "#b2182b", linewidth = pmin(agg2$n / 260, 2.2), alpha = 0.45) +
  geom_point(data = Vv, aes(x = 0.02, y = y), colour = "#2166ac", size = 1.9) +
  geom_point(data = Hh, aes(x = 0.98, y = y), colour = "#e08214", size = 1.9) +
  geom_text(data = Vv, aes(x = -0.02, y = y, label = shorten(virus)), hjust = 1, size = 1.9, colour = INK) +
  geom_text(data = Hh, aes(x = 1.02, y = y, label = shorten(host)), hjust = 0, size = 1.9, colour = INK) +
  scale_x_continuous(limits = c(-0.62, 1.62), expand = expansion(mult = c(0, 0))) +
  scale_y_continuous(limits = c(-0.05, 1.05), expand = expansion(mult = c(0, 0))) +
  labs(title = "B  Host\u2013virus association network", x = NULL, y = NULL) +
  theme_void(base_size = 6.5, base_family = "Arial") +
  theme(plot.title = element_text(size = 7.2, face = "bold", hjust = 0, margin = margin(b = 3)),
        plot.margin = margin(3, 4, 3, 4))

# =============================== Panel C =====================================
# WSSV VP28 AlphaFold model (Q9ICB7, 204 aa): C-alpha trace, coloured by pLDDT.
l <- readLines(file.path(DAT, "vp28_Q9ICB7.pdb"))
ca <- l[substr(l, 1, 4) == "ATOM" & trimws(substr(l, 13, 16)) == "CA"]
st <- data.frame(
  res = as.integer(substr(ca, 23, 26)),
  x = as.numeric(substr(ca, 31, 38)), y = as.numeric(substr(ca, 39, 46)),
  z = as.numeric(substr(ca, 47, 54)), plddt = as.numeric(substr(ca, 61, 66)))
# fixed oblique 3-D projection (not PCA) so the fold reads as a ribbon
az <- -35 * pi / 180; el <- 22 * pi / 180
R <- matrix(c(cos(az), 0, sin(az), 0, 1, 0, -sin(az), 0, cos(az)), 3, 3)
P <- as.matrix(st[, c("x", "y", "z")]) %*% R
st$px <- P[, 1]; st$py <- P[, 2] * cos(el) - P[, 3] * sin(el); st$depth <- P[, 2] * sin(el) + P[, 3] * cos(el)
seg <- data.frame(x = head(st$px, -1), y = head(st$py, -1), xend = st$px[-1], yend = st$py[-1],
                  plddt = head(st$plddt, -1))
plddt_ramp <- c("#FF7D45", "#FFDB13", "#65CBF3", "#0053D6")   # AlphaFold: very low -> very high
pC1 <- ggplot() +
  geom_segment(data = seg, aes(x = x, y = y, xend = xend, yend = yend, colour = plddt),
               linewidth = 1.05, lineend = "round") +
  scale_colour_gradientn(colours = plddt_ramp, limits = c(0, 100), name = "pLDDT") +
  coord_equal() + labs(title = "C  Representative structure (WSSV VP28)") +
  theme_void(base_size = 6.5, base_family = "Arial") +
  theme(plot.title = element_text(size = 7.2, face = "bold", hjust = 0, margin = margin(b = 2)),
        legend.position = "right", legend.title = element_text(size = 5.0),
        legend.text = element_text(size = 4.8), legend.key.size = unit(0.20, "cm"),
        plot.margin = margin(2, 2, 2, 2))
pC2 <- ggplot(st, aes(res, plddt)) +
  geom_col(aes(fill = plddt), width = 1) +
  scale_fill_gradientn(colours = plddt_ramp, limits = c(0, 100)) +
  geom_hline(yintercept = 70, linetype = 2, linewidth = 0.3, colour = GREY) +
  annotate("text", x = 2, y = 74, label = "pLDDT 70", hjust = 0, size = 1.6, colour = GREY) +
  scale_y_continuous(limits = c(0, 100), breaks = c(0, 50, 100)) +
  labs(x = "Residue", y = "pLDDT") +
  theme(legend.position = "none", axis.title = element_text(size = 5.6),
        axis.text = element_text(size = 5.0))
pC <- pC1 / pC2 + plot_layout(heights = c(2.4, 1))

# =============================== Panel D =====================================
eg <- fromJSON(file.path(DAT, "evidence_graph_1.json"))
cn <- eg$categories$name
nd <- data.frame(id = eg$nodes$id, name = eg$nodes$name, cat = eg$nodes$category,
                 val = if ("value" %in% names(eg$nodes)) eg$nodes$value else NA_real_,
                 stringsAsFactors = FALSE)
lk <- data.frame(source = eg$links$source, target = eg$links$target,
                 value = if ("value" %in% names(eg$links)) eg$links$value else 1,
                 stringsAsFactors = FALSE)
CAT_COL <- c("1" = "#2166ac", "2" = "#7f2704", "3" = "#0f766e", "4" = "#54278f",
             "5" = "#8b96a3", "6" = "#b2182b")
# sector layout: category k occupies an arc proportional to its node count; virus at centre
cats <- sort(unique(nd$cat[nd$cat != 0]))
cnt <- sapply(cats, function(k) sum(nd$cat == k))
gap <- 0.05
span <- 2 * pi * (1 - gap * length(cats)) * (cnt / sum(cnt))
start <- cumsum(c(0, head(span, -1))) + cumsum(c(0, rep(gap * 2 * pi, length(cats) - 1)))
nd$ang <- NA_real_
for (i in seq_along(cats)) {
  k <- cats[i]; idx <- which(nd$cat == k)
  nd$ang[idx] <- start[i] + if (length(idx) == 1) span[i] / 2 else seq(0.02, span[i] - 0.02, length.out = length(idx))
}
nd$ang[nd$cat == 0] <- 0
rad <- ifelse(nd$cat == 0, 0, 1)
nd$x <- rad * cos(nd$ang); nd$y <- rad * sin(nd$ang)
pos <- setNames(nd$ang, nd$id)
lk$s <- pos[lk$source]; lk$t <- pos[lk$target]
# link endpoints: centre (0,0) -> node on unit circle
lk$x  <- cos(lk$s) * ifelse(is.na(lk$s), 0, 1); lk$y  <- sin(lk$s) * ifelse(is.na(lk$s), 0, 1)
lk$xend <- nd$x[match(lk$target, nd$id)]; lk$yend <- nd$y[match(lk$target, nd$id)]
lk$xs <- nd$x[match(lk$source, nd$id)]; lk$ys <- nd$y[match(lk$source, nd$id)]
lk$w  <- sqrt(pmax(lk$value, 1))
nd$labs <- ifelse(nd$cat %in% c(0, 2, 3), nd$name, "")
# label anchor
nd$lj <- ifelse(cos(nd$ang) > 0.05, "left", ifelse(cos(nd$ang) < -0.05, "right", "centre"))
nd$lx <- nd$x * 1.06; nd$ly <- nd$y * 1.06
nd$sz <- ifelse(is.na(nd$val), 1.0, pmin(0.6 + sqrt(pmax(nd$val, 0)) / 9, 3.4))
lk$lw <- pmin(sqrt(pmax(lk$value, 1)) / 11, 1.5)
pD <- ggplot() +
  geom_segment(data = lk, aes(x = xs, y = ys, xend = xend, yend = yend),
               colour = "#c9ccd1", linewidth = lk$lw) +
  geom_point(data = nd[nd$cat != 0, ], aes(x = x, y = y, colour = as.character(cat), size = sz)) +
  geom_point(data = nd[nd$cat == 0, ], aes(x = x, y = y), colour = INK, size = 3.2) +
  geom_text(data = nd, aes(x = lx, y = ly, label = labs, hjust = lj), size = 1.5, colour = INK, lineheight = 0.9) +
  scale_colour_manual(values = CAT_COL, labels = cn[as.integer(names(CAT_COL)) + 1], name = NULL) +
  scale_size_identity() +
  coord_equal(xlim = c(-1.75, 1.75), ylim = c(-1.45, 1.45), clip = "off") +
  labs(title = "D  Aggregated evidence graph (WSSV; 3,062 records)") +
  theme_void(base_size = 6.5, base_family = "Arial") +
  theme(plot.title = element_text(size = 7.2, face = "bold", hjust = 0, margin = margin(b = 2)),
        legend.position = "bottom", legend.text = element_text(size = 5.0),
        legend.key.size = unit(0.18, "cm"), plot.margin = margin(2, 4, 2, 4)) +
  guides(colour = guide_legend(override.aes = list(size = 1.7), nrow = 2))

# =============================== Panel E =====================================
E <- gTree(children = gList(
  roundrectGrob(x = 0.72, y = 0.5, width = 0.40, height = 0.62, r = unit(2, "mm"),
                gp = gpar(fill = "#eef3f8", col = "#b8c4d0", lwd = 0.6)),
  textGrob("Curated BLAST snapshot", x = 0.72, y = 0.74, gp = gpar(fontsize = 6.6, fontface = "bold", col = INK)),
  textGrob(sprintf("%s nucleotide\n+ %s protein sequences\nbuilt 2026-10-05",
                   formatC(N[["BLAST_NT"]], big.mark = ","), formatC(N[["BLAST_AA"]], big.mark = ",")),
           x = 0.72, y = 0.47, gp = gpar(fontsize = 5.4, col = GREY, lineheight = 1.25)),
  do.call(gList, lapply(seq_along(c("blastn", "blastp", "blastx", "tblastn")), function(i) {
    yy <- 0.82 - (i - 1) * 0.21
    gTree(children = gList(
      textGrob(c("blastn", "blastp", "blastx", "tblastn")[i], x = 0.10, y = yy, gp = gpar(fontsize = 5.6, col = INK)),
      segmentsGrob(x0 = 0.24, x1 = 0.50, y0 = yy, y1 = yy,
                   arrow = arrow(type = "closed", length = unit(1.1, "mm")), gp = gpar(col = "#0f766e", lwd = 0.7))))
  }))
))
pE <- wrap_elements(full = E) +
  labs(title = "E  BLAST suite against the curated snapshot") +
  theme(plot.title = element_text(size = 7.2, face = "bold", hjust = 0, margin = margin(b = 2)),
        plot.margin = margin(4, 4, 4, 4))

# =============================== assemble ====================================
fig <- (pA) / (pB | pC) / (pD | pE) +
  plot_layout(heights = c(0.95, 1.02, 1.03)) +
  plot_annotation(
    title = "Fig. 5  Analysis and visualization tools of AquaVir-KB",
    caption = paste0(
      "A, RdRp-based family assignment for 1,213 sequences (865 high, 156 medium, 192 low confidence); the 12 most frequent predicted families are shown. ",
      "The phylogeny at right is a representative IQ-TREE maximum-likelihood tree of crustacean Marnaviridae-like RdRp sequences. ",
      "The classification set overlaps the curated RdRp protein list on the website (/rdrp, 776) by 124 sequences. B, host\u2013virus associations restricted to the confirmed-infection (736) and disease-associated (1,749) tiers; ",
      "the 10 viruses and 14 hosts with the most records are shown, edge width scaling with record count. C, predicted structure of WSSV VP28 (UniProt Q9ICB7; 204 aa; AlphaFold model, mean pLDDT 50.9), ",
      "C\u03b1 trace coloured by per-residue pLDDT (bottom: profile; dashed line = 70). Domains are present (WSSV_Vp28, IPR022004/IPR037251) but the source provides no coordinates, so they are not drawn to scale. ",
      "The full set of 6,203 predicted structures is not shown. D, aggregated evidence graph for WSSV built from 3,062 manually checked evidence records (the analysis set). ",
      "E, BLAST suite (blastn, blastp, blastx, tblastn) against the curated snapshot of 5,911 nucleotide and 28,956 protein sequences (built 2026-10-05)."),
    theme = theme(plot.title = element_text(size = 10.5, face = "bold", hjust = 0, family = "Arial"),
                  plot.caption = element_text(size = 4.6, hjust = 0, colour = "#444444", family = "Arial",
                                              margin = margin(t = 6), lineheight = 1.4)))

W <- 7.4; H <- 9.4
svglite(file.path(OUT, "Fig5_analysis_R.svg"), width = W, height = H, bg = "white")
print(fig); dev.off()
cairo_pdf(file.path(OUT, "Fig5_analysis_R.pdf"), width = W, height = H, family = "Arial", bg = "white")
print(fig); dev.off()
agg_tiff(file.path(OUT, "Fig5_analysis_R.tiff"), width = W, height = H, units = "in", res = 600, background = "white")
print(fig); dev.off()
agg_png(file.path(OUT, "Fig5_analysis_R.png"), width = W, height = H, units = "in", res = 300, background = "white")
print(fig); dev.off()
cat("saved R figure 5 (5-panel)\n")
