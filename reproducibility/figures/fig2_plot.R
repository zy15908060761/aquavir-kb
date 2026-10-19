# Fig 2. Content and coverage of AquaVir-KB (iMetaOmics) -- R build.
# Same figure contract as the Python build; R-only rendering (ggplot2 + patchwork).
# Numbers verbatim from TRUTH_TABLE_FIGURES_20261005.md sec.3.
suppressPackageStartupMessages({
  library(ggplot2); library(patchwork); library(dplyr)
  library(scales); library(svglite); library(ragg); library(grid)
})

OUT <- "D:/桌面/AquaVir_Figures_20261005/Fig2"   # canonical submission figure dir

BLUE <- "#2166ac"; BLUE_M <- "#4393c3"; BLUE_L <- "#92c5de"
TEAL <- "#0f766e"; TEAL_L <- "#5ab4ac"; AMBER <- "#c57b0b"
PURPLE <- "#6d5bd0"; GREEN <- "#0f8a5f"; RED <- "#b2182b"
GREY <- "#b8b8b8"; GREY_L <- "#d9d9d9"; GREY_D <- "#8b96a3"

base_theme <- theme_classic(base_size = 6.5, base_family = "Arial") +
  theme(
    axis.line   = element_line(linewidth = 0.35, colour = "black"),
    axis.ticks  = element_line(linewidth = 0.35, colour = "black"),
    axis.title  = element_text(size = 6.5),
    axis.text   = element_text(size = 6, colour = "black"),
    plot.title  = element_text(size = 7, face = "bold", hjust = 0, margin = margin(b = 3)),
    legend.title = element_blank(),
    legend.text = element_text(size = 5.6),
    legend.key.size = unit(0.26, "cm"),
    legend.margin = margin(0, 0, 0, 0),
    legend.spacing.y = unit(0.02, "cm"),
    plot.margin = margin(3, 6, 3, 4),
    panel.grid  = element_blank()
  )
theme_set(base_theme)

# ---- data -------------------------------------------------------------------
DISCOVERY <- data.frame(
  lab = c("survey", "with host evid.", "environmental", "isolated / cultured", "disease outbreak", "other"),
  n   = c(409, 221, 139, 4, 3, 3))
GENOME <- data.frame(
  lab = c("ssRNA(+)", "dsDNA", "dsRNA", "ssDNA", "ssRNA", "ssRNA(-)"),
  n   = c(582, 90, 48, 28, 18, 13))
YEARS <- data.frame(
  year = c(2016,2014,2015,2012,2004,2021,2007,2020,2024,2010),
  n    = c(271,228,153,117,111,97,92,88,84,83))
HOSTS <- data.frame(
  class  = c("Malacostraca","Bivalvia","Gastropoda","Anthozoa","Holothuroidea","Echinoidea",
             "Cephalopoda","Demospongiae","Polychaeta","Branchiopoda","Insecta","Hydrozoa",
             "Asteroidea","other (6 taxa)"),
  n      = c(83,26,11,6,5,4,4,4,2,2,2,2,1,6),
  phylum = c("Arthropoda","Mollusca","Mollusca","Cnidaria","Echinodermata","Echinodermata",
             "Mollusca","Porifera","Annelida","Arthropoda","Arthropoda","Cnidaria",
             "Echinodermata","Other"))
COUNTRIES <- data.frame(
  country = c("China","France","Japan","Canada","India","United States","Mexico","Australia","Thailand","Serbia"),
  n = c(1065,828,302,254,211,191,169,125,125,93))
FAMILIES <- data.frame(
  fam = c("Picornaviridae","Unassigned","Caliciviridae","Yanviridae","Solemoviridae","Totiviridae",
          "Dicistroviridae","Parvoviridae","Flaviviridae","Unclassified","Astroviridae","Weiviridae",
          "Malacoherpesviridae","Circoviridae","Zhaoviridae","Nimaviridae","Narnaviridae","Lispiviridae",
          "Qinviridae","Tombusviridae"),
  n = c(150,139,75,43,40,37,32,23,22,21,20,19,12,11,10,8,7,7,6,5),
  kind = c("A","U","A","A","A","A","A","A","A","C","A","A","A","A","A","A","A","A","A","A"))
PHY_COL <- c(Arthropoda=BLUE, Mollusca=TEAL, Cnidaria=AMBER, Echinodermata=PURPLE,
             Porifera=GREEN, Annelida=RED, Other=GREY)

# ---- donut ------------------------------------------------------------------
donut <- function(d, cols, title) {
  d$lab <- factor(d$lab, levels = d$lab)
  tot <- sum(d$n)
  pv <- d$n / tot * 100
  # non-zero categories below 1% must not read as "0%": one decimal place for those
  pct <- ifelse(pv > 0 & pv < 1,
                sprintf("%s  %.1f%%", as.character(d$lab), pv),
                sprintf("%s  %.0f%%", as.character(d$lab), pv))
  ggplot(d, aes(x = 2, y = n, fill = lab)) +
    geom_col(width = 1, colour = "white", linewidth = 0.35) +
    scale_fill_manual(values = setNames(cols, levels(d$lab)), labels = pct) +
    coord_polar(theta = "y", start = 0) +
    xlim(0.5, 2.5) +
    annotate("text", x = 0.5, y = 0, label = "779", size = 3.4, fontface = "bold", family = "Arial") +
    labs(title = title) +
    theme_void(base_size = 6.5, base_family = "Arial") +
    theme(plot.title = element_text(size = 7, face = "bold", hjust = 0, margin = margin(b = 2)),
          legend.title = element_blank(),
          legend.text = element_text(size = 5.6),
          legend.key.size = unit(0.26, "cm"),
          legend.margin = margin(0, 0, 0, 0),
          legend.spacing.y = unit(0.02, "cm"),
          plot.margin = margin(3, 3, 3, 3))
}

pA <- donut(DISCOVERY, c(BLUE, BLUE_M, BLUE_L, AMBER, RED, GREY), "A  Discovery context")
pD <- donut(GENOME, c(BLUE, TEAL, TEAL_L, AMBER, BLUE_L, PURPLE), "D  Genome type")

# ---- F: sampling years ------------------------------------------------------
pF <- ggplot(YEARS, aes(x = factor(year, levels = sort(year)), y = n)) +
  geom_col(fill = BLUE, width = 0.68) +
  geom_text(aes(label = n), vjust = -0.35, size = 1.9) +
  scale_y_continuous(expand = expansion(mult = c(0, 0.16))) +
  labs(title = "F  Sampling years (top 10)",
       x = NULL, y = "Dated records") +
  theme(axis.text.x = element_text(angle = 45, hjust = 1, size = 5.8))

# ---- B: host composition ----------------------------------------------------
pB <- HOSTS %>%
  mutate(lab = ifelse(phylum == "Other", class,
                      paste0(class, " (", tolower(substr(phylum, 1, 3)), ")"))) %>%
  ggplot(aes(x = reorder(lab, n), y = n, fill = phylum)) +
  geom_col(width = 0.7) +
  geom_text(aes(label = n), hjust = -0.18, size = 1.9) +
  coord_flip() +
  scale_fill_manual(values = PHY_COL) +
  scale_y_continuous(expand = expansion(mult = c(0, 0.15))) +
  labs(title = "B  Host composition by class (158 host entries, 8 phyla)",
       x = NULL, y = "Host entries") +
  theme(axis.text.y = element_text(size = 5.9), legend.position = c(0.82, 0.30))

# ---- E: top families --------------------------------------------------------
pE <- FAMILIES %>%
  mutate(fam = factor(fam, levels = rev(fam))) %>%
  ggplot(aes(x = fam, y = n, fill = kind)) +
  geom_col(width = 0.72) +
  geom_text(aes(label = n), hjust = -0.18, size = 1.9) +
  coord_flip() +
  scale_fill_manual(values = c(A = BLUE, U = GREY, C = GREY_L),
                    labels = c(A = "assigned", U = "unassigned", C = "'Unclassified'")) +
  scale_y_continuous(expand = expansion(mult = c(0, 0.16))) +
  labs(title = "E  Top virus families (of 779)", x = NULL, y = "Core target viruses") +
  theme(axis.text.y = element_text(size = 5.9),
        legend.position = "bottom", legend.direction = "horizontal",
        legend.key.size = unit(0.22, "cm"), legend.text = element_text(size = 5.2),
        legend.margin = margin(0, 0, 0, 0), legend.box.spacing = unit(0.04, "cm"),
        legend.box.margin = margin(0, 0, 0, 0))

# ---- C: countries -----------------------------------------------------------
pC <- COUNTRIES %>%
  ggplot(aes(x = reorder(country, n), y = n)) +
  geom_col(fill = TEAL, width = 0.7) +
  geom_text(aes(label = comma(n)), hjust = -0.18, size = 1.9) +
  coord_flip() +
  scale_y_continuous(expand = expansion(mult = c(0, 0.15)), labels = comma) +
  labs(title = "C  Top sampling countries (of 62)", x = NULL, y = "Sampling records")

# ---- assemble ---------------------------------------------------------------
design <- "ADFF
BBEE
CCEE"
fig <- wrap_plots(pA, pB, pC, pD, pE, pF) +   # order A..F maps design letters
  plot_layout(design = design) +
  plot_annotation(
    title = "Fig. 2  Content and coverage of AquaVir-KB",
    caption = paste0(
      "A, discovery context of the 779 core target viruses. B, host composition (158 host entries across 8 phyla), coloured by phylum. C, sampling countries. D, genome types.\n",
      "E, twenty most frequent virus families; 139 entries have no assigned family. F, ten most sampled years (2,196 dated records, 1983-2025). All counts from the frozen baseline (2026-10-05)."),
    theme = theme(
      plot.title = element_text(size = 10.5, face = "bold", hjust = 0, family = "Arial"),
      plot.caption = element_text(size = 6.2, hjust = 0, colour = "#444444", family = "Arial",
                                  margin = margin(t = 6), lineheight = 1.5)))

W <- 7.8; H <- 5.9
svglite(file.path(OUT, "Fig2_content_coverage_R.svg"), width = W, height = H)
print(fig); dev.off()
cairo_pdf(file.path(OUT, "Fig2_content_coverage_R.pdf"), width = W, height = H, family = "Arial")
print(fig); dev.off()
agg_tiff(file.path(OUT, "Fig2_content_coverage_R.tiff"), width = W, height = H, units = "in", res = 600)
print(fig); dev.off()
agg_png(file.path(OUT, "Fig2_content_coverage_R.png"), width = W, height = H, units = "in", res = 300)
print(fig); dev.off()
cat("saved R figure\n")
