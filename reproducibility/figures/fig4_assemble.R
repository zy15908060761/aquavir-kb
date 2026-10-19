# Fig 4 route A: composite of live-site page renders (Playwright -> PNG), assembled with grid.
# Read-only: the panels are screenshots of the public site; the vector page exports are kept
# alongside in src/fig4_data/.
suppressPackageStartupMessages({ library(grid); library(png); library(magick); library(svglite); library(ragg) })

BASE <- "D:/桌面/AquaVir_Figures_20261005"
DAT  <- file.path(BASE, "src", "fig4_data")
OUT  <- file.path(BASE, "Fig4")

INK <- "#1a1a1a"; GREY <- "#5b6470"
LBL <- c("(A)  Keyword search with faceted filtering", "(B)  Virus detail page (white spot syndrome virus)",
         "(C)  Host page with host-ecology context", "(D)  Data download page (FASTA / XLSX / CSV + SHA-256 manifest)")
IMGS <- c("4a_search.png", "4b_virus.png", "4c_host.png", "4d_download.png")
SMALL <- file.path(DAT, "_small"); dir.create(SMALL, showWarnings = FALSE)
for (f in IMGS) {                                  # downscale for embedding (memory)
  o <- file.path(SMALL, f)
  if (!file.exists(o)) magick::image_write(magick::image_resize(magick::image_read(file.path(DAT, f)), "1400x"), o)
}

W <- 7.4; H <- 7.0
draw <- function() {
  pushViewport(viewport(xscale = c(0, 1), yscale = c(0, 1), clip = "off"))
  grid.rect(gp = gpar(fill = "white", col = NA))
  grid.text("Figure 4. Web interface of AquaVir-KB", x = unit(0.012, "npc"), y = unit(0.985, "npc"),
            just = c("left", "top"), gp = gpar(fontsize = 11, fontface = "bold", col = INK))
  grid.text("Panels rendered from the live site (https://aquavirdb.com); read-only, no site state changed.",
            x = unit(0.012, "npc"), y = unit(0.962, "npc"), just = c("left", "top"),
            gp = gpar(fontsize = 5.9, col = GREY))

  xc <- c(0.255, 0.745); yc <- c(0.748, 0.320)
  cw <- 0.472; ch <- 0.391
  for (i in 1:4) {
    col <- if (i %in% c(1, 3)) 1 else 2
    row <- if (i <= 2) 1 else 2
    img <- readPNG(file.path(SMALL, IMGS[i]))
    grid.text(LBL[i], x = unit(xc[col] - cw / 2 + 0.004, "npc"), y = unit(yc[row] + ch / 2 + 0.022, "npc"),
              just = c("left", "bottom"), gp = gpar(fontsize = 6.6, fontface = "bold", col = INK))
    vp <- viewport(x = unit(xc[col], "npc"), y = unit(yc[row], "npc"),
                   width = unit(cw, "npc"), height = unit(ch, "npc"))
    pushViewport(vp)
    grid.rect(gp = gpar(fill = NA, col = "#c9ccd1", lwd = 0.5))
    grid.raster(img, width = unit(1, "npc"), height = unit(1, "npc"), interpolate = TRUE)
    popViewport()
  }
  grid.text("Panels are renderings of the deployed pages; a vector redraw alternative is provided separately (Fig4_*_redraw).",
            x = unit(0.012, "npc"), y = unit(0.018, "npc"), just = c("left", "bottom"),
            gp = gpar(fontsize = 5.0, col = "#444444"))
  popViewport()
}

svglite(file.path(OUT, "Fig4_web_routeA_live.svg"), width = W, height = H, bg = "white"); draw(); dev.off()
cairo_pdf(file.path(OUT, "Fig4_web_routeA_live.pdf"), width = W, height = H, family = "Arial", bg = "white"); draw(); dev.off()
agg_tiff(file.path(OUT, "Fig4_web_routeA_live.tiff"), width = W, height = H, units = "in", res = 300, background = "white"); draw(); dev.off()
agg_png(file.path(OUT, "Fig4_web_routeA_live.png"), width = W, height = H, units = "in", res = 300, background = "white"); draw(); dev.off()
cat("saved Fig4 route A composite\n")
