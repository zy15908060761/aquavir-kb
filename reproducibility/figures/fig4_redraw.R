# Fig 4 route B: vector redraw of the four key AquaVir-KB screens (grid, pure vector).
# Layouts follow the deployed templates (templates/templates/*.html); text is representative
# of the live pages but simplified. No screenshots -- everything is drawn as vectors.
suppressPackageStartupMessages({ library(grid); library(svglite); library(ragg) })

BASE <- "D:/桌面/AquaVir_Figures_20261005"; OUT <- file.path(BASE, "Fig4")

INK <- "#1a1a1a"; GREY <- "#6b7280"; LINE <- "#d7dde5"
NAVY <- "#2b4b7d"; BLUE <- "#2f6fd0"; ORANGE <- "#e8821e"; TEAL <- "#12a08a"; PURPLE <- "#7a5bd0"
u <- function(v) unit(v, "npc")
s <- function(v) unit(v, "native")

tx <- function(x, y, label, size = 2.7, col = INK, ff = "plain", just = "centre", lh = 1.0)
  grid.text(label, x = s(x), y = s(y), gp = gpar(fontsize = size, col = col, fontface = ff, lineheight = lh), just = just)
bx <- function(x0, x1, y0, y1, fill = "white", col = LINE, lwd = 0.4, r = 0.6)
  grid.roundrect(x = s((x0 + x1) / 2), y = s((y0 + y1) / 2), width = s(x1 - x0), height = s(y1 - y0),
                 r = unit(r, "mm"), gp = gpar(fill = fill, col = col, lwd = lwd))
btn <- function(x0, y0, w, h, label, col = BLUE, tcol = "white", size = 2.4) {
  bx(x0, x0 + w, y0, y0 + h, fill = col, col = col); tx(x0 + w / 2, y0 + h / 2, label, size = size, col = tcol, ff = "bold")
}
hdr <- function(nav = TRUE) {
  grid.rect(x = s(50), y = s(96.5), width = s(100), height = s(7), gp = gpar(fill = NAVY, col = NA))
  grid.rect(x = s(4.5), y = s(96.5), width = s(2.6), height = s(2.6), gp = gpar(fill = "white", col = NA))
  tx(7, 96.5, "AquaVir-KB", size = 3.4, col = "white", ff = "bold", just = "left")
  if (nav) {
    items <- c("Home", "Search", "Viruses", "Hosts", "Taxonomy", "Statistics", "BLAST", "Download")
    for (i in seq_along(items)) tx(20 + (i - 1) * 8.6, 96.5, items[i], size = 2.2, col = "#dbe4f2")
    bx(88, 99, 94.5, 98.5, fill = "white", col = "white")
    tx(88.6, 96.5, "Search database", size = 2.0, col = GREY, just = "left")
  }
}
lines <- function(x0, x1, y, n, gap = 1.7, size = 2.2, col = "#9aa3ad", w = c(1, 0.82, 0.9, 0.7)) {
  for (i in 1:n) grid.segments(x0 = s(x0), x1 = s(x0 + (x1 - x0) * w[(i - 1) %% length(w) + 1]),
                               y0 = s(y - (i - 1) * gap), y1 = s(y - (i - 1) * gap), gp = gpar(col = col, lwd = 0.5))
}

# ---- Panel A: search --------------------------------------------------------
draw_search <- function() {
  hdr()
  bx(6, 94, 84.5, 91, fill = "#f7f9fc"); tx(7.5, 87.7, "\u201cwhite spot syndrome\u201d", size = 2.8, just = "left")
  btn(86.5, 85.2, 7, 5.2, "Search")
  for (i in 1:4) { bx(6 + (i - 1) * 22.3, 6 + (i - 1) * 22.3 + 20.5, 77, 82, fill = "white") }
  for (i in 1:4) tx(7 + (i - 1) * 22.3, 79.5, c("All Phyla", "All Families", "All Completeness", "All Countries")[i],
                    size = 2.2, col = GREY, just = "left")
  bx(6, 27, 46, 74, fill = "#fbfcfe")
  tx(8, 71.5, "FILTER STATS", size = 2.4, ff = "bold", just = "left")
  tx(8, 68, "Total results", size = 2.1, col = GREY, just = "left"); tx(25, 68, "1,199", size = 2.4, ff = "bold", just = "right")
  tx(8, 64.5, "Total claims", size = 2.1, col = GREY, just = "left"); tx(25, 64.5, "1,199", size = 2.4, ff = "bold", just = "right")
  tx(8, 61, "Current page", size = 2.1, col = GREY, just = "left"); tx(25, 61, "1 / 60", size = 2.4, ff = "bold", just = "right")
  tx(8, 56, "white spot syndrome", size = 2.1, col = BLUE, just = "left")
  bx(30, 97, 46, 74, fill = "white")
  cols <- c("Accession", "Virus name", "Host", "Country", "Year", "Length")
  xs <- c(32, 44, 68, 80, 90, 96)
  for (i in seq_along(cols)) tx(xs[i], 71.5, cols[i], size = 2.05, col = GREY, ff = "bold", just = "left")
  grid.segments(x0 = s(31), x1 = s(96), y0 = s(70), y1 = s(70), gp = gpar(col = LINE, lwd = 0.5))
  for (r in 0:11) {
    y <- 67.5 - r * 1.85
    tx(32, y, sprintf("AB85%04d", 742 - r), size = 1.95, col = BLUE, just = "left")
    tx(44, y, ifelse(r %% 3 == 2, "White spot syndrome virus", "White spot syndrome virus"), size = 1.95, just = "left")
    tx(68, y, c("Litopenaeus vannamei", "Penaeus monodon", "Marsupenaeus japonicus")[r %% 3 + 1], size = 1.95, col = GREY, just = "left")
    tx(80, y, c("China", "Vietnam", "Canada")[r %% 3 + 1], size = 1.95, col = GREY, just = "left")
    tx(90, y, 2020 + (r %% 5), size = 1.95, col = GREY, just = "left")
    tx(96, y, sprintf("%4d aa", 300 + r * 17), size = 1.95, col = GREY, just = "left")
    if (r < 11) grid.segments(x0 = s(31), x1 = s(96), y0 = s(y - 0.9), y1 = s(y - 0.9), gp = gpar(col = "#eef1f4", lwd = 0.4))
  }
  tx(63.5, 44, "1  2  3  4  ...  Next \u203a", size = 2.1, col = BLUE)
}

# ---- Panel B: virus detail --------------------------------------------------
draw_virus <- function() {
  hdr()
  tx(6, 89.5, "Home  \u203a  Search  \u203a  White spot syndrome virus", size = 2.0, col = GREY, just = "left")
  tx(6, 85, "White spot syndrome virus", size = 4.2, ff = "bold", just = "left")
  for (i in 1:3) bx(6 + (i - 1) * 12, 6 + (i - 1) * 12 + 11, 79, 82.5, fill = "#eef3fb", col = "#dbe6f7")
  for (i in 1:3) tx(11.5 + (i - 1) * 12, 80.8, c("Nimaviridae", "Arthropoda", "dsDNA")[i], size = 2.1, col = NAVY)
  cards <- list(c("Length", "119 aa"), c("GC content", "49.61"), c("Completeness", "partial sequence"),
                c("Country", "26"), c("Year", "2013"), c("Isolates", "1,188"), c("Hosts", "41"))
  for (i in seq_along(cards)) {
    x <- 6 + (i - 1) * 13.1
    bx(x, x + 12.3, 67.5, 77, fill = "#fbfcfe")
    tx(x + 6.1, 74.5, cards[[i]][1], size = 1.95, col = GREY); tx(x + 6.1, 70.5, cards[[i]][2], size = 2.7, ff = "bold")
  }
  bx(6, 62, 46, 64, fill = "#fbfcfe"); tx(7.5, 55, "Outbreak Events", size = 2.5, ff = "bold", just = "left"); lines(7.5, 58, 51, 3)
  bx(63.5, 97, 47, 62, fill = "#fbfcfe"); tx(65, 59, "ICTV Mapping", size = 2.5, ff = "bold", just = "left"); lines(65, 95, 55, 4)
  bx(6, 62, 22, 44, fill = "#fbfcfe"); tx(7.5, 40.5, "Reference", size = 2.5, ff = "bold", just = "left"); lines(7.5, 60, 36.5, 4)
  bx(63.5, 97, 22, 44, fill = "#fbfcfe"); tx(65, 40.5, "Genome & Source", size = 2.5, ff = "bold", just = "left"); lines(65, 95, 36.5, 6)
  bx(6, 97, 6, 20, fill = "#fbfcfe"); tx(7.5, 17, "Reviewed Evidence", size = 2.5, ff = "bold", just = "left")
  for (i in 1:5) tx(7.5, 13.6 - (i - 1) * 1.7, paste0("Evidence record ", i, "  \u2014  auto-extracted, manually checked"), size = 1.95, col = GREY, just = "left")
}

# ---- Panel C: host detail ---------------------------------------------------
draw_host <- function() {
  hdr()
  tx(6, 89.5, "Home  \u203a  Hosts  \u203a  Litopenaeus vannamei", size = 2.0, col = GREY, just = "left")
  tx(6, 85, "Litopenaeus vannamei", size = 4.0, ff = "bold", just = "left")
  tx(6, 81, "Order Decapoda  \u00b7  Family Penaeidae  \u00b7  Habitat marine/brackish", size = 2.1, col = GREY, just = "left")
  stats <- c("1,602", "160", "33"); lab <- c("Isolates", "Associated viruses", "Countries")
  for (i in 1:3) { x <- 30 + (i - 1) * 23; bx(x, x + 21, 78, 86.5, fill = "#fbfcfe")
    tx(x + 10.5, 83, stats[i], size = 3.4, ff = "bold"); tx(x + 10.5, 79.8, lab[i], size = 2.0, col = GREY) }
  bx(6, 27, 30, 76, fill = "#fbfcfe"); tx(7.5, 72.5, "HOST PROFILE", size = 2.4, ff = "bold", just = "left"); lines(7.5, 25, 68, 5)
  bx(6, 27, 8, 28, fill = "#fbfcfe"); tx(7.5, 24.5, "EXTERNAL DATA", size = 2.4, ff = "bold", just = "left"); lines(7.5, 25, 20, 4)
  bx(30, 97, 8, 76, fill = "white"); tx(31.5, 72.5, "ASSOCIATED VIRUSES (160)", size = 2.4, ff = "bold", just = "left")
  for (i in 1:5) {
    y0 <- 66 - (i - 1) * 11.5; bx(31.5, 95.5, y0, y0 + 9.5, fill = "#fbfcfe")
    tx(33, y0 + 6.8, c("White spot syndrome virus", "Taura syndrome virus", "Laem-Singh virus", "Wenzhou shrimp virus", "Infectious hypodermal and hematopoietic necrosis virus")[i], size = 2.15, ff = "bold", just = "left")
    tx(33, y0 + 3.4, c("Nimaviridae", "Dicistroviridae", "Loniviridae", "Unclassified", "Parvoviridae")[i], size = 1.95, col = GREY, just = "left")
    tx(90, y0 + 5, c("884", "271", "45", "33", "29")[i], size = 2.1, col = GREY)
    btn(87, y0 + 0.4, 8, 3, "View", col = "#eef3fb", tcol = NAVY, size = 1.9)
  }
}

# ---- Panel D: download ------------------------------------------------------
draw_download <- function() {
  hdr()
  tx(6, 89, "Data Download", size = 4.0, ff = "bold", just = "left")
  tx(6, 85, "Only release-filtered public datasets are listed.", size = 2.1, col = GREY, just = "left")
  bx(6, 94, 78, 83, fill = "#fbfcfe")
  tx(7.5, 80.5, "All data is released under Creative Commons Attribution 4.0 (CC BY 4.0); you are free to share and adapt the data for any purpose, provided you give appropriate credit.", size = 1.95, col = GREY, just = "left")
  cards <- list(list("Standardized Metadata", "#2f6fd0", "Curated, publication-quality isolate metadata\nwith source-reference information. (540 KB)", "Download Excel"),
                list("All Curated Sequences", "#e8821e", "FASTA sequences for strictly filtered,\npublication-quality isolates only. (32 MB)", "Download FASTA"),
                list("Complete Genomes", "#12a08a", "Publication-quality sequences of reasonable length,\nannotated as complete genomes. (19 MB)", "Download FASTA"),
                list("Reviewed Evidence", "#e8821e", "86,160 manually checked evidence records\nwith PMID/DOI provenance. (4.82 MB Excel)", "Download Excel"),
                list("Host-Virus Network", "#7a5bd0", "Publication-quality host-virus association edge table,\nsuited for network analysis tools. (49 KB)", "Download CSV"))
  pos <- list(c(6, 33), c(34.5, 61.5), c(63, 90.5), c(6, 33), c(34.5, 61.5))
  yy  <- c(52, 52, 52, 9, 9)
  for (i in seq_along(cards)) {
    x0 <- pos[[i]][1]; x1 <- pos[[i]][2]; y0 <- yy[i]; y1 <- y0 + 34
    bx(x0, x1, y0, y1, fill = "white")
    grid.rect(x = s(x0 + 2.6), y = s(y1 - 3.2), width = s(4), height = s(4), gp = gpar(fill = cards[[i]][[2]], col = NA))
    tx(x0 + 1.5, y1 - 8.5, cards[[i]][[1]], size = 2.9, ff = "bold", just = "left")
    tx(x0 + 1.5, y1 - 15, cards[[i]][[3]], size = 2.0, col = GREY, just = "left", lh = 1.15)
    btn(x0 + 1.5, y0 + 3, 14, 4.6, cards[[i]][[4]], col = cards[[i]][[2]], size = 2.1)
    btn(x0 + 16, y0 + 3, 9, 4.6, "View format", col = "#eef3fb", tcol = NAVY, size = 1.9)
  }
}

# ---- assemble ---------------------------------------------------------------
W <- 7.4; H <- 7.6
draw <- function() {
  pushViewport(viewport(xscale = c(0, 1), yscale = c(0, 1), clip = "off"))
  grid.rect(gp = gpar(fill = "white", col = NA))
  grid.text("Figure 4. Web interface of AquaVir-KB", x = u(0.012), y = u(0.988), just = c("left", "top"),
            gp = gpar(fontsize = 11, fontface = "bold", col = INK))
  grid.text("Vector-illustrated redrawings of the four key screens (search, virus detail, host detail, download); drawn to scale from the deployed templates, not raw screenshots.",
            x = u(0.012), y = u(0.966), just = c("left", "top"), gp = gpar(fontsize = 5.7, col = GREY))
  labs <- c("(A)  Keyword search with faceted filtering", "(B)  Virus detail page (white spot syndrome virus)",
            "(C)  Host page with host-ecology context", "(D)  Data download page (FASTA / XLSX / CSV + SHA-256 manifest)")
  xc <- c(0.255, 0.745); yc <- c(0.730, 0.335); cw <- 0.472; ch <- 0.362
  fns <- list(draw_search, draw_virus, draw_host, draw_download)
  for (i in 1:4) {
    col <- if (i %% 2 == 1) 1 else 2; row <- if (i <= 2) 1 else 2
    grid.text(labs[i], x = u(xc[col] - cw / 2 + 0.004), y = u(yc[row] + ch / 2 + 0.024), just = c("left", "bottom"),
              gp = gpar(fontsize = 6.6, fontface = "bold", col = INK))
    pushViewport(viewport(x = u(xc[col]), y = u(yc[row]), width = u(cw), height = u(ch),
                          xscale = c(0, 100), yscale = c(0, 100), clip = "on"))
    grid.rect(gp = gpar(fill = "white", col = LINE, lwd = 0.5))
    fns[[i]]()
    popViewport()
  }
  grid.text("Text is representative of the live pages; layout, colours and elements follow the deployed templates.",
            x = u(0.012), y = u(0.016), just = c("left", "bottom"), gp = gpar(fontsize = 5.0, col = "#444444"))
  popViewport()
}

svglite(file.path(OUT, "Fig4_web_routeB_redraw.svg"), width = W, height = H, bg = "white"); draw(); dev.off()
cairo_pdf(file.path(OUT, "Fig4_web_routeB_redraw.pdf"), width = W, height = H, family = "Arial", bg = "white"); draw(); dev.off()
agg_tiff(file.path(OUT, "Fig4_web_routeB_redraw.tiff"), width = W, height = H, units = "in", res = 600, background = "white"); draw(); dev.off()
agg_png(file.path(OUT, "Fig4_web_routeB_redraw.png"), width = W, height = H, units = "in", res = 300, background = "white"); draw(); dev.off()
cat("saved Fig4 route B redraw\n")
