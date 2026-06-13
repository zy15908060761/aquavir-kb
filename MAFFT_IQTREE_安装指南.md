# MAFFT + IQ-TREE 手动安装指南 (Windows)

## 方式一：Windows 原生安装（推荐，最简单）

### 1. MAFFT

1. 打开浏览器，访问: https://mafft.cbrc.jp/alignment/software/windows_portable.html
2. 点击下载 `mafft-7.526-win64-signed.zip`（约 15 MB）
3. 解压到 `F:\mafft\` 目录
4. 验证安装: 打开 PowerShell，运行:
   ```
   F:\mafft\mafft.bat --version
   ```

### 2. IQ-TREE

1. 打开浏览器，访问: https://github.com/iqtree/iqtree2/releases
2. 找到最新版（v2.4.0 以上），下载 `iqtree-2.4.0-Windows.zip`
3. 解压到 `F:\iqtree\` 目录
4. 验证安装: 打开 PowerShell，运行:
   ```
   F:\iqtree\bin\iqtree2.exe --version
   ```

### 3. 确认安装成功

打开 PowerShell:
```
F:\mafft\mafft.bat --version
F:\iqtree\bin\iqtree2.exe --version
```

两行都有输出就装好了，告诉我，我立刻跑分析。

---

## 方式二：WSL 安装（备选，网络通了的话更快）

打开 PowerShell 或 CMD:
```
wsl                    # 进入 Ubuntu
sudo apt-get update    # 更新包列表
sudo apt-get install -y mafft iqtree   # 安装
mafft --version        # 验证
iqtree --version       # 验证
exit                   # 退出 WSL
```

---

> 推荐方式一。下载完解压到 F 盘根目录，全程 5 分钟。两个文件加起来不到 30 MB。
