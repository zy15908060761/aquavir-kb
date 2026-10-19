# Fig 1. Architecture and data flow of AquaVir-KB -- R build (grid + svglite).
# Figure contract: a single curated resource assembled from public sources, cleaned into a
# reviewed evidence base, integrated in one SQLite database, and served for browsing/analysis.
# Four stacked bands (A data sources / B extraction & cleaning / C integration / D application)
# connected by downward flow arrows. All numbers are verbatim from the v0.5 review manuscript
# Figure 1 legend (deliverables/DRAFT_老师审阅初稿_v0.5.md) and TRUTH_TABLE_FIGURES_20261005.md sec.2.
suppressPackageStartupMessages({
  library(grid); library(svglite); library(ragg)
})

OUT <- "D:/桌面/AquaVir_Figures_20261005/Fig1"   # canonical submission figure dir

INK   <- "#1a1a1a"
GREY  <- "#5b6470"
COL_A <- "#2166ac"   # data sources
COL_B <- "#0f766e"   # extraction & cleaning
COL_C <- "#54278f"   # integration
COL_D <- "#b2182b"   # application

tint <- function(hex, f = 0.90) {          # blend toward white; f = fraction white
  r <- strtoi(substr(hex, 2, 3), 16) / 255
  g <- strtoi(substr(hex, 4, 5), 16) / 255
  b <- strtoi(substr(hex, 6, 7), 16) / 255
  rgb(r + (1 - r) * f, g + (1 - g) * f, b + (1 - b) * f)
}
u <- function(v) unit(v, "npc")

# ---- drawing helpers --------------------------------------------------------
node <- function(xc, yc, w, h, lab, col, fs = 4.5, fillf = 0.90) {
  grid.roundrect(x = u(xc), y = u(yc), width = u(w), height = u(h), r = unit(1.2, "mm"),
                 gp = gpar(fill = tint(col, fillf), col = tint(col, 0.55), lwd = 0.5))
  grid.text(lab, x = u(xc), y = u(yc),
            gp = gpar(fontsize = fs, col = INK, lineheight = 1.02))
}

band <- function(x0, x1, y0, y1, col, tag, title, note = NULL) {
  grid.roundrect(x = u((x0 + x1) / 2), y = u((y0 + y1) / 2),
                 width = u(x1 - x0), height = u(y1 - y0), r = unit(1.6, "mm"),
                 gp = gpar(fill = tint(col, 0.965), col = tint(col, 0.55), lwd = 0.7))
  grid.rect(x = u(x0 + 0.016), y = u(y1 - 0.020), width = u(0.020), height = u(0.022),
            gp = gpar(fill = col, col = NA))                       # colour bullet
  grid.text(paste0(tag, "  ", title), x = u(x0 + 0.032), y = u(y1 - 0.020),
            just = c("left", "centre"),
            gp = gpar(fontsize = 7.4, fontface = "bold", col = col))
  if (!is.null(note))
    grid.text(note, x = u(x1 - 0.010), y = u(y1 - 0.020), just = c("right", "centre"),
              gp = gpar(fontsize = 4.8, col = GREY))
}

flow_arrow <- function(x, y0, y1, col, lwd = 1.1, len = 1.6) {
  grid.segments(x0 = u(x), y0 = u(y0), x1 = u(x), y1 = u(y1),
                arrow = arrow(type = "closed", length = unit(len, "mm")),
                gp = gpar(col = col, lwd = lwd, fill = col))
}
flow_arrow_h <- function(y, x0, x1, col, lwd = 0.9, len = 1.4) {
  grid.segments(x0 = u(x0), y0 = u(y), x1 = u(x1), y1 = u(y),
                arrow = arrow(type = "closed", length = unit(len, "mm")),
                gp = gpar(col = col, lwd = lwd, fill = col))
}

# ---- figure -----------------------------------------------------------------
W <- 7.4; H <- 7.9
draw <- function() {
  pushViewport(viewport(xscale = c(0, 1), yscale = c(0, 1), clip = "off"))
  grid.rect(gp = gpar(fill = "white", col = NA))

  grid.text("Figure 1. Architecture and data flow of AquaVir-KB",
            x = u(0.012), y = u(0.988), just = c("left", "top"),
            gp = gpar(fontsize = 11, fontface = "bold", col = INK))
  grid.text("A single curated resource, assembled from public sources, cleaned into a reviewed evidence base, integrated in one SQLite database, and served for browsing and analysis.",
            x = u(0.012), y = u(0.964), just = c("left", "top"),
            gp = gpar(fontsize = 5.9, col = GREY))

  XL <- 0.035; XR <- 0.985

  # ---- band A: data sources -------------------------------------------------
  A0 <- 0.715; A1 <- 0.930
  band(XL, XR, A0, A1, COL_A, "(A)", "Data sources", "primary sequence, taxonomy, literature and annotation sources")
  r1 <- c("NCBI GenBank\n6,257 ingested records", "ICTV MSL41\n17,554 taxa",
          "ICTV VMR\n19,271 records", "WOAH 2024\n18 disease mappings",
          "Europe PMC / PubMed\n9,069 refs (+101)", "UniProt\n11,351 protein links")
  r2 <- c("AlphaFold\n6,203 structures", "InterPro\n71,964 annotations",
          "KEGG\n18,620 annotations", "GBIF\n4,039 occurrences", "OBIS\n2,885 occurrences")
  nh <- 0.046; gap <- 0.014
  yc1 <- A1 - 0.072; yc2 <- A1 - 0.152
  for (i in seq_along(r1)) {
    w <- (XR - XL - gap * (length(r1) - 1)) / length(r1)
    node(XL + (i - 1) * (w + gap) + w / 2, yc1, w, nh, r1[i], COL_A)
  }
  for (i in seq_along(r2)) {
    w <- (XR - XL - gap * (length(r2) - 1)) / length(r2)
    node(XL + (i - 1) * (w + gap) + w / 2, yc2, w, nh, r2[i], COL_A)
  }

  # ---- band B: extraction and cleaning --------------------------------------
  B0 <- 0.400; B1 <- 0.665
  band(XL, XR, B0, B1, COL_B, "(B)", "Extraction and cleaning", "raw records \u2192 the reviewed analysis set")
  by1 <- B1 - 0.067; by2 <- B1 - 0.145; by3 <- B1 - 0.223
  nhB <- 0.048
  # evidence
  node(0.115, by1, 0.155, nhB, "353,160\nraw evidence records", COL_B)
  flow_arrow_h(by1, 0.196, 0.232, COL_B)
  node(0.335, by1, 0.150, nhB, "93,168\nanalysis set", COL_B, fillf = 0.80)
  grid.text("106,594 rejected  \u00b7  93,180 manual-checked, of which 12 lack a reference and are excluded",
            x = u(0.425), y = u(by1), just = c("left", "centre"), gp = gpar(fontsize = 4.5, col = GREY))
  # isolates
  node(0.115, by2, 0.155, nhB, "17,867\nisolate records", COL_B)
  flow_arrow_h(by2, 0.196, 0.232, COL_B)
  node(0.335, by2, 0.150, nhB, "5,403\nstrict target isolates", COL_B, fillf = 0.80)
  grid.text("+ 8,008 metagenomic candidates held separately",
            x = u(0.425), y = u(by2), just = c("left", "centre"), gp = gpar(fontsize = 4.5, col = GREY))
  # hosts
  node(0.095, by3, 0.115, nhB, "278\nimported", COL_B)
  flow_arrow_h(by3, 0.156, 0.188, COL_B)
  node(0.255, by3, 0.115, nhB, "244\npublic", COL_B)
  flow_arrow_h(by3, 0.316, 0.348, COL_B)
  node(0.415, by3, 0.130, nhB, "159\nwith curated virus association", COL_B, fillf = 0.80)
  grid.text("host entries, retained after public filtering and association curation",
            x = u(0.492), y = u(by3), just = c("left", "centre"), gp = gpar(fontsize = 4.5, col = GREY))

  flow_arrow(0.51, B1 + 0.004, A0 - 0.004, GREY)     # A -> B

  # ---- band C: integration --------------------------------------------------
  C0 <- 0.245; C1 <- 0.360
  band(XL, XR, C0, C1, COL_C, "(C)", "Integration layer", "one portable database")
  node(0.510, 0.298, 0.900, 0.052,
       "SQLite single-file database  \u00b7  481 schema objects: 139 tables  \u00b7  46 views  \u00b7  3 triggers  \u00b7  293 indexes  \u00b7  9 schema versions",
       COL_C, fs = 4.9)
  flow_arrow(0.51, C1 + 0.004, B0 - 0.004, GREY)     # B -> C

  # ---- band D: application --------------------------------------------------
  D0 <- 0.120; D1 <- 0.205
  band(XL, XR, D0, D1, COL_D, "(D)", "Application layer", "")
  dlab <- c("Search, browse\nand detail pages", "Bulk downloads\n+ SHA-256 manifest",
            "Analysis modules\n(phylogeny, network)", "REST API")
  gapD <- 0.016
  for (i in seq_along(dlab)) {
    w <- (XR - XL - gapD * 3) / 4
    node(XL + (i - 1) * (w + gapD) + w / 2, 0.152, w, 0.054, dlab[i], COL_D)
  }
  flow_arrow(0.51, D1 + 0.004, C0 - 0.004, GREY)     # C -> D

  grid.text(paste0(
    "Numbers as reported in the manuscript. (A) Primary sources ingested by the build pipeline. ",
    "(B) Raw evidence is reduced to the manually checked analysis set, isolates to strictly curated target\n",
    "isolates, and host entries to those carrying a curated virus association. (C) All layers are integrated in a single SQLite file. ",
    "(D) The database is exposed through a web application and a REST API."),
    x = u(0.012), y = u(0.100), just = c("left", "top"),
    gp = gpar(fontsize = 5.0, col = "#444444", lineheight = 1.35))

  popViewport()
}

svglite(file.path(OUT, "Fig1_architecture.svg"), width = W, height = H, bg = "white")
draw(); dev.off()
cairo_pdf(file.path(OUT, "Fig1_architecture.pdf"), width = W, height = H, family = "Arial", bg = "white")
draw(); dev.off()
agg_tiff(file.path(OUT, "Fig1_architecture.tiff"), width = W, height = H, units = "in", res = 600, background = "white")
draw(); dev.off()
agg_png(file.path(OUT, "Fig1_architecture.png"), width = W, height = H, units = "in", res = 300, background = "white")
draw(); dev.off()
cat("saved R figure 1 (four-layer architecture)\n")
