# 999fpsx — CPU Tuner and Power Plan Manager 🐣⚙️

A tiny, friendly Windows app (EXE) for safe CPU tuning, live telemetry, and power‑plan management. Dark theme, profiles, optional vendor CLI support, and a rollback safety timer so you can experiment without fear.

---

### What it is

- **Live telemetry**: real‑time CPU frequency, temperature, and load graphs.  
- **Safe Windows tuning**: preview and apply Windows power settings (max processor state, core parking, affinity).  
- **Profiles**: save and load settings as editable profiles; optionally include a Windows power plan file.  
- **Auto import**: import and optionally activate a `.pow` power plan at startup.  
- **Vendor CLI support**: optional integration to call vendor tools (AMD/Intel) if you install them.  
- **Safety features**: rollback timer and explicit preview so changes can be reverted automatically.

---

### Quick start for 999FPSX 🚀

1. **Place the EXE somewhere convenient** (Desktop or Program Files).  
2. **Run the EXE** by double‑clicking it.  
3. **To change system power plans or vendor settings** run the EXE as **Administrator**: right‑click the EXE and choose **Run as administrator**.  
4. **Open the app** and watch the left side graphs for a minute to see baseline behavior.  
5. **Make changes on the right**, click **Preview Changes** to review, then click **Apply Settings** to apply them. The app starts a rollback timer so you can confirm stability.  
6. **Save a profile** by entering a name and clicking **Save**. Check **Include power plan (.pow)** if you want the current Windows plan exported with the profile.  
7. **Use Auto Import Plan** to point the app to a `.pow` file and enable activation on startup if desired.

---

### How to use the app step by step 🧭

1. **Observe**  
   - Let the telemetry run for 1–2 minutes to see normal temps and load.  
2. **Tweak safely**  
   - Change one setting at a time. Click **Preview Changes** to see the exact actions the app will run.  
3. **Apply with safety**  
   - Click **Apply Settings**. The rollback timer begins. If something goes wrong, wait for the timer or click **Revert**.  
4. **Save your setup**  
   - Save the current settings as a profile so you can reapply them later. Optionally export the Windows power plan with the profile.  
5. **Auto import power plan**  
   - If you have a `.pow` file you trust, set it in **Auto Import Plan** and enable **Activate after import**. The app will import and optionally activate it at startup (Admin required).  
6. **Vendor tools (optional)**  
   - If you installed a vendor CLI (for example AMD Ryzen Master CLI), set its path in **Vendor Control**, enter a vendor profile or command template, and click **Apply Vendor Profile**. Only use this if you know the vendor CLI syntax.

---

### Settings explained for beginners 📘

| **Setting** | **What it changes** | **When to use it** |
|---|---:|---|
| **Thermal cutoff** | Auto‑revert when CPU reaches this temperature | Set to protect the CPU; 90–95°C is a safe starting point |
| **Max processor state AC / DC** | Windows cap on CPU boost percentage | **100%** for full performance; **99%** to reduce peak boost and lower temps/noise |
| **Disable core parking** | Prevents Windows from parking idle logical cores | Check for gaming to reduce micro‑stutter |
| **Telemetry interval** | How often graphs update | 0.5–1.0 s is responsive without much overhead |
| **Affinity mode** | Pin processes to specific logical cores | Advanced; leave at **all** unless testing a specific game |
| **Rollback window** | Seconds before auto‑revert | Keep enabled until you confirm stability (20–60 s recommended) |
| **Include power plan (.pow)** | Export the active Windows plan with a profile | Use to reproduce exact Windows power settings later |
| **Vendor CLI path / template** | Path and command template for vendor tools | Advanced; only set if you installed vendor CLI and tested commands |
| **PL1 / PL2** | Power limits applied via vendor CLI if supported | Advanced; only use with vendor CLI and safe values |

**Tips for Ryzen**  

- Start with **Max processor state = 100%**, **Disable core parking = checked**, **Thermal cutoff = 90–95°C**. If you want quieter temps, try **99%** and test performance.

---

### Safety and troubleshooting 🛡️

- **Run as Administrator** for power plan import/activation and vendor CLI actions.  
- **Use the rollback timer** until you confirm stability. If something feels wrong, click **Revert**.  
- **Test changes incrementally**: change one thing, run a game or stress test for a few minutes.  
- **Profiles are JSON**: they store app settings. If you want a Windows power plan saved with a profile, check **Include power plan (.pow)** when saving.  
- **Vendor CLI commands vary**: test vendor CLI commands manually in an elevated command prompt before automating them in the app.  
- **Logs**: open `999fpsx.log` in the app folder for detailed messages if something fails.

---
