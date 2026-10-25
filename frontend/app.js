/*
 * SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

/**
 * @fileoverview Voice Highlighter single-page web application frontend.
 *
 * Implements real-time interactive subtitle layout canvas preview, typography and
 * style controls, preset management (load, save, delete, dirty tracking), video
 * metadata inspection, job queuing, progress polling, in-browser dialogue editing,
 * and direct video burning and playback triggers.
 *
 * Adheres strictly to AGENTS.md directives: zero external CDNs, local bundled assets,
 * WCAG 2.1 AA keyboard accessibility, and XDG configuration synchronization.
 */

document.addEventListener("DOMContentLoaded", () => {
  // State
  const state = {
    videoPath: (document.getElementById("videoPathInput") ? document.getElementById("videoPathInput").value.trim() : "") || "",
    videoMeta: null,
    hasLoadedVideo: false,
    currentSeekTime: 0.0,
    isPlaying: false,
    currentDialogueLineText: null,
    keyframes: [],
    activeKeyframeId: null,
    selectedKeyframeId: null,
    isAtKeyframe: false,
    basePresetStyling: null,
    lastBurnedVideoPath: null,
    posX: 50,
    posY: 78,
    fontFamily: "Montserrat",
    fontSize: 68,
    bold: true,
    italic: false,
    textBaseColor: "#FFFFFF",
    outlineColor: "#000000",
    outlineWidth: 3.5,
    highlightStyle: "color", // 'color' or 'box'
    highlightColor: "#FFDF00",
    highlightScalePct: 100, // 100% to 180% active word font boost
    highlightAnimation: "discrete", // 'discrete', 'karaoke_wipe', or 'anticipation_glow'
    boxType: "word", // 'word' or 'block'
    boxBgColor: "#000000",
    boxOpacity: 0.85,
    boxFontColor: "#FFFFFF",
    maxLines: 1,
    maxChars: 28,
    lineWidthPct: 82,
    outputMode: "ass", // 'ass' or 'burn'
    outputFilename: "",
    socialPlatform: "none", // 'none', 'youtube', 'instagram', 'facebook'
    socialDevice: "mobile", // 'mobile', 'web'
    previewText: "Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt.",
    activeWordIndex: 0,
    currentTaskId: null,
    pollInterval: null,
    hasExistingAss: false,
    existingAssPath: null,
    existingAssName: null,
    lastBurnedVideoPath: null,
    lastBurnedVideoFilename: null,
    hasExistingWav: false,
    existingWavPath: null,
    // Multi-Speaker Color Channels & Acoustic Diarization (Track B)
    enableDiarization: false,
    speakerSamples: {},
    speakerCount: 1,
    detectedSpeakers: ["Speaker 1"],
    isMultiSpeaker: false,
    activeSpeakerId: "SPEAKER_00",
    speakerChannels: {
      "SPEAKER_00": {
        id: "SPEAKER_00",
        name: "Speaker 1",
        primary_color: "#FFFFFF",
        highlight_color: "#FFDF00",
        outline_color: "#000000",
        box_bg_color: "#000000",
        box_font_color: "#FFFFFF",
        show_speaker_name: false
      },
      "SPEAKER_01": {
        id: "SPEAKER_01",
        name: "Speaker 2",
        primary_color: "#FFFFFF",
        highlight_color: "#00E5FF",
        outline_color: "#000000",
        box_bg_color: "#000000",
        box_font_color: "#FFFFFF",
        show_speaker_name: false
      },
      "SPEAKER_02": {
        id: "SPEAKER_02",
        name: "Speaker 3",
        primary_color: "#FFFFFF",
        highlight_color: "#FF007F",
        outline_color: "#000000",
        box_bg_color: "#000000",
        box_font_color: "#FFFFFF",
        show_speaker_name: false
      },
      "SPEAKER_03": {
        id: "SPEAKER_03",
        name: "Speaker 4",
        primary_color: "#FFFFFF",
        highlight_color: "#00FF66",
        outline_color: "#000000",
        box_bg_color: "#000000",
        box_font_color: "#FFFFFF",
        show_speaker_name: false
      },
      "SPEAKER_04": {
        id: "SPEAKER_04",
        name: "Speaker 5",
        primary_color: "#FFFFFF",
        highlight_color: "#B026FF",
        outline_color: "#000000",
        box_bg_color: "#000000",
        box_font_color: "#FFFFFF",
        show_speaker_name: false
      }
    },
    stylingModified: false,
    showBounds: false,
    customVocabulary: []
  };

  function getCurrentStylingPayload() {
    const payload = {
      font_name: state.fontFamily,
      font_size: state.fontSize,
      bold: state.bold,
      italic: state.italic,
      primary_color: state.textBaseColor,
      outline_color: state.outlineColor,
      outline_width: state.outlineWidth,
      highlight_style: state.highlightStyle,
      highlight_color: state.highlightColor,
      highlight_scale_pct: state.highlightScalePct,
      highlight_animation: state.highlightAnimation || "discrete",
      box_type: state.boxType,
      box_bg_color: state.boxBgColor,
      box_opacity: state.boxOpacity,
      box_font_color: state.boxFontColor,
      pos_x_pct: state.posX,
      pos_y_pct: state.posY,
      max_lines: state.maxLines,
      max_chars_per_line: state.maxChars,
      line_width_pct: state.lineWidthPct,
      custom_vocabulary: Array.isArray(state.customVocabulary) ? [...state.customVocabulary] : [],
      keyframes: (state.keyframes && state.keyframes.length > 0) ? JSON.parse(JSON.stringify(state.keyframes)) : []
    };
    if (state.isMultiSpeaker && state.speakerCount >= 2 && state.speakerChannels) {
      const activeChannels = {};
      const spkKeys = Object.keys(state.speakerChannels).slice(0, state.speakerCount);
      spkKeys.forEach(k => {
        activeChannels[k] = state.speakerChannels[k];
      });
      payload.speaker_channels = JSON.parse(JSON.stringify(activeChannels));
    }
    return payload;
  }

  // DOM Elements
  const videoPathInput = document.getElementById("videoPathInput");
  const stagePlaceholder = document.getElementById("stagePlaceholder");
  const stagePoster = document.getElementById("stagePoster");
  const stageVideo = document.getElementById("stageVideo");
  const videoStage = document.getElementById("videoStage");
  const subtitleDragBox = document.getElementById("subtitleDragBox");
  const subtitleRenderedText = document.getElementById("subtitleRenderedText");
  const safeZoneOverlay = document.getElementById("safeZoneOverlay");
  const btnPlayPause = document.getElementById("btnPlayPause");
  const playIcon = document.getElementById("playIcon");
  const playLabel = document.getElementById("playLabel");
  const btnToggleBounds = document.getElementById("btnToggleBounds");
  const subtitleBoundsEnvelope = document.getElementById("subtitleBoundsEnvelope");
  const boundsBadge = document.getElementById("boundsBadge");
  const boundsGuidelines = document.getElementById("boundsGuidelines");
  const metaRes = document.getElementById("metaRes");
  const metaDuration = document.getElementById("metaDuration");

  // Burned Video Delivery DOM Elements
  const burnedDeliveryBanner = document.getElementById("burnedDeliveryBanner");
  const burnedVideoPathText = document.getElementById("burnedVideoPathText");
  const btnCopyBurnedPath = document.getElementById("btnCopyBurnedPath");
  const copyBurnedBtnText = document.getElementById("copyBurnedBtnText");
  const btnOpenVideo = document.getElementById("btnOpenVideo");

  // Timeline Frame Scrubber & Scene Jump Tray Elements
  const stageTimelineWrap = document.getElementById("stageTimelineWrap");
  const stageTimelineSlider = document.getElementById("stageTimelineSlider");
  const timelineCurrentTime = document.getElementById("timelineCurrentTime");
  const timelineTotalDuration = document.getElementById("timelineTotalDuration");
  const btnStepBack5 = document.getElementById("btnStepBack5");
  const btnStepBack1 = document.getElementById("btnStepBack1");
  const btnStepFwd1 = document.getElementById("btnStepFwd1");
  const btnStepFwd5 = document.getElementById("btnStepFwd5");
  const sceneFilmstripWrap = document.getElementById("sceneFilmstripWrap");
  const sceneFilmstripTray = document.getElementById("sceneFilmstripTray");
  const timelineEmptyHint = document.getElementById("timelineEmptyHint");

  // Timeline Keyframe Controls & Overlay Elements
  const timelineKeyframeControls = document.getElementById("timelineKeyframeControls");
  const btnPrevKeyframe = document.getElementById("btnPrevKeyframe");
  const btnAddKeyframe = document.getElementById("btnAddKeyframe");
  const btnDeleteKeyframe = document.getElementById("btnDeleteKeyframe");
  const btnNextKeyframe = document.getElementById("btnNextKeyframe");
  const keyframeCountBadge = document.getElementById("keyframeCountBadge");
  const timelineTrackContainer = document.getElementById("timelineTrackContainer");
  const timelineKeyframesTrack = document.getElementById("timelineKeyframesTrack");
  const timelineKeyframeBanner = document.getElementById("timelineKeyframeBanner");
  const keyframeBannerText = document.getElementById("keyframeBannerText");
  const keyframeBannerHint = document.getElementById("keyframeBannerHint");

  function updateStageVisibility() {
    if (!state.hasLoadedVideo) {
      if (stagePlaceholder) stagePlaceholder.classList.remove("hidden");
      if (stagePoster) {
        stagePoster.classList.add("hidden");
        stagePoster.src = "";
      }
      if (subtitleDragBox) subtitleDragBox.classList.add("hidden");
      if (subtitleBoundsEnvelope) subtitleBoundsEnvelope.classList.add("hidden");
      if (safeZoneOverlay) safeZoneOverlay.classList.add("hidden");
      if (socialUiLayer) socialUiLayer.classList.add("hidden");
      if (metaRes) metaRes.textContent = "Resolution: --";
      if (metaDuration) metaDuration.textContent = "Duration: --";

      // Reset Playback Controls
      if (btnPlayPause) {
        btnPlayPause.disabled = true;
        updatePlayPauseUI(false);
      }
      if (stageVideo) {
        stageVideo.pause();
        stageVideo.src = "";
        stageVideo.classList.add("hidden");
      }

      // Reset Timeline Scrubber to Idle Disabled State
      if (stageTimelineSlider) {
        stageTimelineSlider.disabled = true;
        stageTimelineSlider.value = "0";
      }
      if (timelineCurrentTime) timelineCurrentTime.textContent = "00:00.00";
      if (timelineTotalDuration) timelineTotalDuration.textContent = "00:00.00";
      [btnStepBack5, btnStepBack1, btnStepFwd1, btnStepFwd5].forEach(btn => {
        if (btn) btn.disabled = true;
      });
      if (sceneFilmstripTray) {
        sceneFilmstripTray.innerHTML = '<span class="timeline-empty-hint" id="timelineEmptyHint" style="font-size: 0.74rem; color: var(--text-muted, #94a3b8); font-style: italic; grid-column: span 5; text-align: center; padding: 6px;">Load a video above to scrub scenes and test subtitle placement.</span>';
      }

      // Reset Keyframe Controls
      if (btnAddKeyframe) btnAddKeyframe.disabled = true;
      if (btnDeleteKeyframe) btnDeleteKeyframe.disabled = true;
      if (btnPrevKeyframe) btnPrevKeyframe.disabled = true;
      if (btnNextKeyframe) btnNextKeyframe.disabled = true;
      if (keyframeCountBadge) keyframeCountBadge.style.display = "none";
      if (timelineKeyframesTrack) timelineKeyframesTrack.innerHTML = "";
      if (timelineKeyframeBanner) timelineKeyframeBanner.style.display = "none";
    } else {
      if (stagePlaceholder) stagePlaceholder.classList.add("hidden");
      if (stagePoster) stagePoster.classList.remove("hidden");
      if (subtitleDragBox) subtitleDragBox.classList.remove("hidden");
      if (state.showBounds && subtitleBoundsEnvelope) {
        subtitleBoundsEnvelope.classList.remove("hidden");
        updateBoundsEnvelope();
      }
      if (safeZoneOverlay) safeZoneOverlay.classList.remove("hidden");
      if (state.socialPlatform !== "none" && socialUiLayer) {
        socialUiLayer.classList.remove("hidden");
      }

      // Enable Scrubber and Playback Controls
      if (btnPlayPause) btnPlayPause.disabled = false;
      if (stageTimelineSlider) stageTimelineSlider.disabled = false;
      [btnStepBack5, btnStepBack1, btnStepFwd1, btnStepFwd5].forEach(btn => {
        if (btn) btn.disabled = false;
      });

      // Enable Keyframe Controls
      if (btnAddKeyframe) btnAddKeyframe.disabled = false;
      if (typeof renderTimelineKeyframeMarkers === "function") {
        renderTimelineKeyframeMarkers();
        updateKeyframeToolbarAndBanner(state.currentSeekTime || 0);
      }
    }
  }

  // Sibling Asset DOM Elements
  const badgeExistingWav = document.getElementById("badgeExistingWav");
  const badgeExistingWavText = document.getElementById("badgeExistingWavText");
  const badgeExistingAss = document.getElementById("badgeExistingAss");
  const badgeExistingAssText = document.getElementById("badgeExistingAssText");
  const wrapReuseAssToggle = document.getElementById("wrapReuseAssToggle");
  const chkReuseExistingAss = document.getElementById("chkReuseExistingAss");

  // Word Spelling List (Prevent WhisperX Misspellings)
  const inputCustomVocab = document.getElementById("inputCustomVocab");
  const btnAddVocab = document.getElementById("btnAddVocab");
  const vocabChipsWrap = document.getElementById("vocabChipsWrap");
  const vocabChipsList = document.getElementById("vocabChipsList");
  const vocabEmptyHint = document.getElementById("vocabEmptyHint");
  const vocabCountBadge = document.getElementById("vocabCountBadge");
  const btnHarvestFile = document.getElementById("btnHarvestFile");
  const inputVocabFile = document.getElementById("inputVocabFile");
  const btnSaveVocabFile = document.getElementById("btnSaveVocabFile");
  const btnHarvestSpeakers = document.getElementById("btnHarvestSpeakers");
  const btnClearVocab = document.getElementById("btnClearVocab");

  // Positioning
  const sliderPosY = document.getElementById("sliderPosY");
  const sliderPosX = document.getElementById("sliderPosX");
  const labelPosY = document.getElementById("labelPosY");
  const labelPosX = document.getElementById("labelPosX");
  const presetBtns = document.querySelectorAll(".preset-btn");
  const btnResetPos = document.getElementById("btnResetPos");

  // Font & Style
  const selectFontFamily = document.getElementById("selectFontFamily");
  const sliderFontSize = document.getElementById("sliderFontSize");
  const labelFontSize = document.getElementById("labelFontSize");
  const colorTextBase = document.getElementById("colorTextBase");
  const codeTextBase = document.getElementById("codeTextBase");
  const colorOutline = document.getElementById("colorOutline");
  const codeOutline = document.getElementById("codeOutline");
  const sliderOutlineWidth = document.getElementById("sliderOutlineWidth");
  const labelOutlineWidth = document.getElementById("labelOutlineWidth");
  const checkBold = document.getElementById("checkBold");
  const checkItalic = document.getElementById("checkItalic");

  // Highlight
  const btnStyleColor = document.getElementById("btnStyleColor");
  const btnStyleBox = document.getElementById("btnStyleBox");
  const paneHighlightColor = document.getElementById("paneHighlightColor");
  const paneHighlightBox = document.getElementById("paneHighlightBox");
  const colorHighlightText = document.getElementById("colorHighlightText");
  const codeHighlightText = document.getElementById("codeHighlightText");
  const selectBoxType = document.getElementById("selectBoxType");
  const sliderBoxOpacity = document.getElementById("sliderBoxOpacity");
  const labelBoxOpacity = document.getElementById("labelBoxOpacity");
  const colorBoxBg = document.getElementById("colorBoxBg");
  const codeBoxBg = document.getElementById("codeBoxBg");
  const colorBoxFont = document.getElementById("colorBoxFont");
  const codeBoxFont = document.getElementById("codeBoxFont");
  const swatchBtns = document.querySelectorAll(".swatch-btn");
  const sliderHighlightScale = document.getElementById("sliderHighlightScale");
  const labelHighlightScale = document.getElementById("labelHighlightScale");
  const selectHighlightAnimation = document.getElementById("selectHighlightAnimation");

  // Multi-Speaker Color Channels DOM Elements
  const speakerChannelsSection = document.getElementById("speakerChannelsSection");
  const speakerCountBadge = document.getElementById("speakerCountBadge");
  const btnModeSingleSpeaker = document.getElementById("btnModeSingleSpeaker");
  const btnModeMultiSpeaker = document.getElementById("btnModeMultiSpeaker");
  const btnToggleSpeakerChannels = document.getElementById("btnToggleSpeakerChannels");
  const countPillBtns = document.querySelectorAll(".count-pill-btn");
  const speakerTabsBar = document.getElementById("speakerTabsBar");
  const speakerChannelMeta = document.getElementById("speakerChannelMeta");
  const currentEditingSpeakerName = document.getElementById("currentEditingSpeakerName");
  const currentEditingSpeakerDot = document.getElementById("currentEditingSpeakerDot");
  const inputSpeakerDisplayName = document.getElementById("inputSpeakerDisplayName");
  const colorSpeakerHighlight = document.getElementById("colorSpeakerHighlight");
  const codeSpeakerHighlight = document.getElementById("codeSpeakerHighlight");
  const speakerSwatchChips = document.querySelectorAll(".speaker-swatch-chip");
  const checkEnableDiarization = document.getElementById("checkEnableDiarization");
  const btnPlaySpeakerSample = document.getElementById("btnPlaySpeakerSample");
  const speakerSamplePlayIcon = document.getElementById("speakerSamplePlayIcon");
  const speakerSamplePlayText = document.getElementById("speakerSamplePlayText");
  const speakerSampleQuote = document.getElementById("speakerSampleQuote");
  const speakerSampleAudio = document.getElementById("speakerSampleAudio");
  const speakerSamplePlayerRow = document.getElementById("speakerSamplePlayerRow");

  // Lines & Line Width
  const linePillBtns = document.querySelectorAll("#lineCountSelector .pill-btn");
  const sliderMaxChars = document.getElementById("sliderMaxChars");
  const labelMaxChars = document.getElementById("labelMaxChars");
  const sliderLineWidth = document.getElementById("sliderLineWidth");
  const labelLineWidth = document.getElementById("labelLineWidth");

  // Style Presets & Templates
  const selectPreset = document.getElementById("selectPreset");
  const optgroupCustom = document.getElementById("optgroupCustom");
  const btnApplyPreset = document.getElementById("btnApplyPreset");
  const btnUpdatePreset = document.getElementById("btnUpdatePreset");
  const btnSavePreset = document.getElementById("btnSavePreset");
  const btnRenamePreset = document.getElementById("btnRenamePreset");
  const btnDeletePreset = document.getElementById("btnDeletePreset");
  const btnExportPreset = document.getElementById("btnExportPreset");
  const btnImportPresetTrigger = document.getElementById("btnImportPresetTrigger");
  const presetFileInput = document.getElementById("presetFileInput");
  const presetNameDrawer = document.getElementById("presetNameDrawer");
  const drawerTitle = document.getElementById("drawerTitle");
  const presetNameInput = document.getElementById("presetNameInput");
  const btnConfirmPresetName = document.getElementById("btnConfirmPresetName");
  const btnDismissPresetName = document.getElementById("btnDismissPresetName");
  const btnCancelPresetName = document.getElementById("btnCancelPresetName");
  const presetStatusMsg = document.getElementById("presetStatusMsg");

  // Output Deliverables & Custom Filename
  const outputModeBtns = document.querySelectorAll("#outputModeSelector .pill-btn");
  const outputModeHint = document.getElementById("outputModeHint");
  const outputFilenameInput = document.getElementById("outputFilenameInput");
  const filenameExtBadge = document.getElementById("filenameExtBadge");
  const valActiveAss = document.getElementById("valActiveAss");
  const valActiveVideo = document.getElementById("valActiveVideo");
  const statusActiveAss = document.getElementById("statusActiveAss");
  const statusActiveVideo = document.getElementById("statusActiveVideo");
  const chipActiveAss = document.getElementById("chipActiveAss");
  const chipActiveVideo = document.getElementById("chipActiveVideo");

  /**
   * Synchronize the full filenames and live status of output deliverables (.ass and .mp4).
   * Ensures the user always sees the complete deliverable filenames instead of bare extensions.
   */
  function syncDeliverableFilenames() {
    const rawVal = outputFilenameInput ? outputFilenameInput.value.trim() : "";
    let cleanBase = rawVal || state.outputFilename || "";
    if (cleanBase) {
      cleanBase = cleanBase.replace(/\.(ass|mp4)$/i, "").trim();
    }
    if (!cleanBase) {
      if (state.videoMeta?.base_name) {
        cleanBase = `${state.videoMeta.base_name}_voice_titles`;
      } else {
        cleanBase = "voice_titles";
      }
    }

    // 1. Subtitles Deliverable (.ass)
    if (valActiveAss) {
      if (state.hasExistingAss && state.existingAssName) {
        valActiveAss.textContent = state.existingAssName;
        if (statusActiveAss) {
          statusActiveAss.textContent = "✓ Ready";
          statusActiveAss.className = "deliverable-status-tag ready";
        }
        if (chipActiveAss) {
          chipActiveAss.classList.add("is-ready");
          chipActiveAss.title = `Subtitles deliverable ready: ${state.existingAssName} (Click to inspect & edit words)`;
        }
      } else {
        valActiveAss.textContent = `${cleanBase}.ass`;
        if (statusActiveAss) {
          statusActiveAss.textContent = "Not generated";
          statusActiveAss.className = "deliverable-status-tag pending";
        }
        if (chipActiveAss) {
          chipActiveAss.classList.remove("is-ready");
          chipActiveAss.title = `Target subtitles deliverable: ${cleanBase}.ass (Run Step 1 to generate)`;
        }
      }
    }

    // 2. Burned Video Deliverable (.mp4)
    if (valActiveVideo) {
      if (state.lastBurnedVideoPath) {
        const burnedName = state.lastBurnedVideoFilename || state.lastBurnedVideoPath.split("/").pop();
        valActiveVideo.textContent = burnedName;
        if (statusActiveVideo) {
          statusActiveVideo.textContent = "✓ Ready";
          statusActiveVideo.className = "deliverable-status-tag ready";
        }
        if (chipActiveVideo) {
          chipActiveVideo.classList.add("is-ready");
          chipActiveVideo.title = `Burned video deliverable ready: ${burnedName} (Click to open in player)`;
        }
      } else {
        valActiveVideo.textContent = `${cleanBase}.mp4`;
        if (statusActiveVideo) {
          statusActiveVideo.textContent = "Not burned";
          statusActiveVideo.className = "deliverable-status-tag pending";
        }
        if (chipActiveVideo) {
          chipActiveVideo.classList.remove("is-ready");
          chipActiveVideo.title = `Target burned video deliverable: ${cleanBase}.mp4 (Run Step 3 to burn)`;
        }
      }
    }
  }

  // Interactive chip shortcuts
  if (chipActiveAss) {
    chipActiveAss.addEventListener("click", () => {
      if (state.hasExistingAss && cardAssFileHub) {
        cardAssFileHub.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  }

  if (chipActiveVideo) {
    chipActiveVideo.addEventListener("click", () => {
      if (state.lastBurnedVideoPath) {
        const btnOpenVideo = document.getElementById("btnOpenVideo");
        if (btnOpenVideo) {
          btnOpenVideo.click();
        } else if (burnedDeliveryBanner) {
          burnedDeliveryBanner.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      }
    });
  }

  // Social Media Overlay Controls
  const socialPlatformBtns = document.querySelectorAll("#socialPlatformSelector .mini-pill-btn");
  const socialDeviceBtns = document.querySelectorAll("#socialDeviceSelector .mini-pill-btn");
  const socialUiLayer = document.getElementById("socialUiLayer");

  // Preview Controls
  const btnTextDefault = document.getElementById("btnTextDefault");
  const btnTextLorem = document.getElementById("btnTextLorem");
  const previewTextInput = document.getElementById("previewTextInput");

  // Actions & Results
  const btnSubmit = document.getElementById("btnSubmit");
  const btnSubmitText = document.getElementById("btnSubmitText");
  const btnSubmitSubtext = document.getElementById("btnSubmitSubtext");
  const cardStatus = document.getElementById("cardStatus");
  const progressBarFill = document.getElementById("progressBarFill");
  const statusStageMessage = document.getElementById("statusStageMessage");
  const statusPercent = document.getElementById("statusPercent");
  const cardResults = document.getElementById("cardResults");
  const resultsTitle = document.getElementById("resultsTitle");
  const resultsHint = document.getElementById("resultsHint");
  const btnDownloadVideo = document.getElementById("btnDownloadVideo");
  const btnDownloadAss = document.getElementById("btnDownloadAss");
  const btnDownloadAssText = document.getElementById("btnDownloadAssText");
  const btnCopyAss = document.getElementById("btnCopyAss");
  const copyBtnText = document.getElementById("copyBtnText");
  const codeBodyPreview = document.getElementById("codeBodyPreview");

  // Studio Stepper & Pipeline Elements (Idea #3)
  const cardStudio = document.getElementById("cardStudio");
  const chipPipelineStatus = document.getElementById("chipPipelineStatus");
  const wfStep1 = document.getElementById("wfStep1");
  const wfStep2 = document.getElementById("wfStep2");
  const wfStep3 = document.getElementById("wfStep3");
  const wfSub1 = document.getElementById("wfSub1");
  const wfSub2 = document.getElementById("wfSub2");
  const wfSub3 = document.getElementById("wfSub3");
  const btnGenerateAssOnly = document.getElementById("btnGenerateAssOnly");
  const titleGenerateAss = document.getElementById("titleGenerateAss");
  const descGenerateAss = document.getElementById("descGenerateAss");
  const btnBurnOnly = document.getElementById("btnBurnOnly");
  const btnTranscribeAndBurn = document.getElementById("btnTranscribeAndBurn");

  // Step 2: Subtitle File & External Editor Hub Elements
  const cardAssFileHub = document.getElementById("cardAssFileHub");
  const assFileStatusBadge = document.getElementById("assFileStatusBadge");
  const assFilenameDisplay = document.getElementById("assFilenameDisplay");
  const assFilePathDisplay = document.getElementById("assFilePathDisplay");
  const assDialogueCountDisplay = document.getElementById("assDialogueCountDisplay");
  const assFileSizeDisplay = document.getElementById("assFileSizeDisplay");
  const assMtimeDisplay = document.getElementById("assMtimeDisplay");
  const btnOpenInTextEditor = document.getElementById("btnOpenInTextEditor");
  const btnShowInFileManager = document.getElementById("btnShowInFileManager");
  const btnCopyAssPath = document.getElementById("btnCopyAssPath");
  const btnRefreshAssFromDisk = document.getElementById("btnRefreshAssFromDisk");

  // Stepper Nodes
  const stepNodeExtract = document.getElementById("stepNodeExtract");
  const stepNodeWhisper = document.getElementById("stepNodeWhisper");
  const stepNodeAlign = document.getElementById("stepNodeAlign");
  const stepNodeAss = document.getElementById("stepNodeAss");
  const stepLine4 = document.getElementById("stepLine4");
  const stepNodeBurn = document.getElementById("stepNodeBurn");

  // Step 2 Action Overview Card Elements
  const btnFocusStep2 = document.getElementById("btnFocusStep2");
  const chipStep2Count = document.getElementById("chipStep2Count");

  // ----------------------------------------------------
  // Dynamic Hardware Engine Display
  // ----------------------------------------------------
  async function fetchSystemInfo() {
    try {
      const res = await fetch("/api/system-info");
      if (!res.ok) return;
      const info = await res.json();
      const badgeWrap = document.getElementById("hardwareBadge");
      const badgeText = document.getElementById("hardwareBadgeText");
      const whisperDevice = document.getElementById("whisperModelDevice");
      const wfSub1 = document.getElementById("wfSub1");
      const wfSub3 = document.getElementById("wfSub3");
      const deliveryEngineTag = document.getElementById("deliveryEngineTag");
      const appVersionBadge = document.getElementById("appVersionBadge");
      const footerVersion = document.getElementById("footerVersion");

      if (info.version) {
        if (appVersionBadge) appVersionBadge.textContent = `v${info.version}`;
        if (footerVersion) footerVersion.textContent = `v${info.version}`;
      }

      if (badgeText && info.active_badge_text) {
        badgeText.textContent = info.active_badge_text;
      }

      if (badgeWrap) {
        badgeWrap.classList.remove("engine-gpu", "engine-cpu");
        if (info.is_gpu) {
          badgeWrap.classList.add("engine-gpu");
        } else {
          badgeWrap.classList.add("engine-cpu");
        }

        let tooltip = `Rendering: ${info.burn_engine}\nTranscription: ${info.whisper_engine}`;
        if (info.gpu_diagnostic) {
          tooltip += `\n⚠️ Note: ${info.gpu_diagnostic}`;
        }
        badgeWrap.title = tooltip;
      }

      if (whisperDevice) {
        whisperDevice.textContent = info.engine_type || (info.is_gpu ? "GPU" : "CPU");
      }
      if (wfSub1 && info.short_engine) {
        wfSub1.textContent = info.whisper_engine || `WhisperX (${info.short_engine})`;
      }
      if (wfSub3 && info.burn_engine) {
        wfSub3.textContent = `${info.burn_engine} (~3s)`;
      }
      if (deliveryEngineTag && info.burn_engine) {
        deliveryEngineTag.textContent = info.burn_engine;
      }
    } catch (err) {
      console.warn("Could not fetch system info:", err);
    }
  }

  // ----------------------------------------------------
  // 1. Native Desktop OS File Dialog & Direct File Loading
  // ----------------------------------------------------
  const btnBrowseFiles = document.getElementById("btnBrowseFiles");
  const btnJumpVideos = document.getElementById("btnJumpVideos");
  const btnJumpProject = document.getElementById("btnJumpProject");

  // Standard directory paths
  const VIDEOS_DIR = "~/Videos";
  const PROJECT_DIR = ".";

  // File Browser Modal Elements
  const modalFileBrowser = document.getElementById("modalFileBrowser");
  const btnCloseFileBrowser = document.getElementById("btnCloseFileBrowser");
  const btnCancelFileBrowser = document.getElementById("btnCancelFileBrowser");
  const btnSelectFileBrowser = document.getElementById("btnSelectFileBrowser");
  const browserCurrentPathDisplay = document.getElementById("browserCurrentPathDisplay");
  const browserFolderList = document.getElementById("browserFolderList");
  const browserFileList = document.getElementById("browserFileList");
  const browserSelectedFileCode = document.getElementById("browserSelectedFileCode");
  const btnBrowserUpDir = document.getElementById("btnBrowserUpDir");
  const btnBrowserRefresh = document.getElementById("btnBrowserRefresh");
  const btnOpenInAppBrowser = document.getElementById("btnOpenInAppBrowser");

  let browserState = {
    currentDir: "",
    parentDir: null,
    selectedFilePath: null
  };

  async function loadBrowserDir(dirPath = null) {
    if (!browserFolderList || !browserFileList) return;
    browserFolderList.innerHTML = `<div class="browser-empty-list"><span class="spinner-sm"></span> Loading folders...</div>`;
    browserFileList.innerHTML = `<div class="browser-empty-list"><span class="spinner-sm"></span> Loading video files...</div>`;
    if (browserSelectedFileCode) browserSelectedFileCode.textContent = "None selected";
    if (btnSelectFileBrowser) {
      btnSelectFileBrowser.disabled = true;
      btnSelectFileBrowser.classList.add("disabled");
    }
    browserState.selectedFilePath = null;

    try {
      const url = "/api/browse-files" + (dirPath ? `?dir=${encodeURIComponent(dirPath)}` : "");
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (!data.success) throw new Error(data.detail || "Failed to read directory");

      browserState.currentDir = data.current_dir;
      browserState.parentDir = data.parent_dir;

      if (browserCurrentPathDisplay) {
        browserCurrentPathDisplay.textContent = data.current_dir;
        browserCurrentPathDisplay.title = data.current_dir;
      }

      if (btnBrowserUpDir) {
        btnBrowserUpDir.disabled = !data.parent_dir;
      }

      // Populate directories
      browserFolderList.innerHTML = "";
      if (!data.directories || data.directories.length === 0) {
        browserFolderList.innerHTML = `<div class="browser-empty-list">No subfolders found</div>`;
      } else {
        data.directories.forEach(d => {
          const item = document.createElement("div");
          item.className = "browser-item";
          item.innerHTML = `
            <div class="browser-item-left">
              <span class="browser-item-icon">📁</span>
              <span class="browser-item-name" title="${d.path}">${d.name}</span>
            </div>
            <span class="browser-item-meta">Dir</span>
          `;
          item.addEventListener("click", () => loadBrowserDir(d.path));
          browserFolderList.appendChild(item);
        });
      }

      // Populate video / audio files
      browserFileList.innerHTML = "";
      if (!data.videos || data.videos.length === 0) {
        browserFileList.innerHTML = `<div class="browser-empty-list">No video/audio files found in this folder</div>`;
      } else {
        data.videos.forEach(f => {
          const item = document.createElement("div");
          item.className = "browser-item";
          const icon = f.ext === ".wav" || f.ext === ".mp3" ? "🎵" : "🎬";
          item.innerHTML = `
            <div class="browser-item-left">
              <span class="browser-item-icon">${icon}</span>
              <span class="browser-item-name" title="${f.path}">${f.name}</span>
            </div>
            <span class="browser-item-meta">${f.size_mb} MB</span>
          `;
          item.addEventListener("click", () => {
            // Unselect all other items
            browserFileList.querySelectorAll(".browser-item").forEach(el => el.classList.remove("active"));
            item.classList.add("active");
            browserState.selectedFilePath = f.path;
            if (browserSelectedFileCode) {
              browserSelectedFileCode.textContent = f.name;
              browserSelectedFileCode.title = f.path;
            }
            if (btnSelectFileBrowser) {
              btnSelectFileBrowser.disabled = false;
              btnSelectFileBrowser.classList.remove("disabled");
            }
          });
          item.addEventListener("dblclick", () => {
            selectAndLoadFile(f.path);
          });
          browserFileList.appendChild(item);
        });
      }
    } catch (err) {
      console.error("Directory browse error:", err);
      if (browserFolderList) browserFolderList.innerHTML = `<div class="browser-empty-list" style="color: #ef4444;">Error: ${err.message}</div>`;
      if (browserFileList) browserFileList.innerHTML = `<div class="browser-empty-list" style="color: #ef4444;">Error: ${err.message}</div>`;
    }
  }

  function openFileBrowserModal(initialDir = null) {
    if (!modalFileBrowser) return;
    modalFileBrowser.classList.remove("hidden");
    loadBrowserDir(initialDir);
  }

  function closeFileBrowserModal() {
    if (modalFileBrowser) modalFileBrowser.classList.add("hidden");
  }

  function selectAndLoadFile(filePath) {
    if (!filePath) return;
    if (videoPathInput) videoPathInput.value = filePath;
    state.videoPath = filePath;
    closeFileBrowserModal();
    loadVideoInfo(filePath);
  }

  // Modal event bindings
  if (btnCloseFileBrowser) btnCloseFileBrowser.addEventListener("click", closeFileBrowserModal);
  if (btnCancelFileBrowser) btnCancelFileBrowser.addEventListener("click", closeFileBrowserModal);
  if (btnSelectFileBrowser) {
    btnSelectFileBrowser.addEventListener("click", () => {
      if (browserState.selectedFilePath) {
        selectAndLoadFile(browserState.selectedFilePath);
      }
    });
  }
  if (btnBrowserUpDir) {
    btnBrowserUpDir.addEventListener("click", () => {
      if (browserState.parentDir) loadBrowserDir(browserState.parentDir);
    });
  }
  if (btnBrowserRefresh) {
    btnBrowserRefresh.addEventListener("click", () => {
      loadBrowserDir(browserState.currentDir);
    });
  }

  // Bookmark chips
  const chipBmVideos = document.getElementById("chipBmVideos");
  const chipBmMovies = document.getElementById("chipBmMovies");
  const chipBmDownloads = document.getElementById("chipBmDownloads");
  const chipBmHome = document.getElementById("chipBmHome");
  const chipBmProject = document.getElementById("chipBmProject");

  if (chipBmVideos) chipBmVideos.addEventListener("click", () => loadBrowserDir("~/Videos"));
  if (chipBmMovies) chipBmMovies.addEventListener("click", () => loadBrowserDir("~/Movies"));
  if (chipBmDownloads) chipBmDownloads.addEventListener("click", () => loadBrowserDir("~/Downloads"));
  if (chipBmHome) chipBmHome.addEventListener("click", () => loadBrowserDir("~"));
  if (chipBmProject) chipBmProject.addEventListener("click", () => loadBrowserDir("."));
  if (btnOpenInAppBrowser) btnOpenInAppBrowser.addEventListener("click", () => openFileBrowserModal());

  async function openNativeFileDialog(initialDir = null) {
    const target = initialDir || (videoPathInput ? videoPathInput.value.trim() : "") || null;
    const originalBrowseHtml = btnBrowseFiles ? btnBrowseFiles.innerHTML : "";
    if (btnBrowseFiles) {
      btnBrowseFiles.disabled = true;
      btnBrowseFiles.innerHTML = `<span class="spinner-sm"></span> <span>Opening Dialog...</span>`;
    }

    try {
      const res = await fetch("/api/open-os-file-dialog", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          initial_path: target,
          title: "Select Video File"
        })
      });
      if (!res.ok) {
        throw new Error(`Server returned status ${res.status}`);
      }
      const data = await res.json();
      if (data.success && !data.cancelled && data.path) {
        if (videoPathInput) videoPathInput.value = data.path;
        state.videoPath = data.path;
        await loadVideoInfo(data.path);
      } else if (data.success && data.cancelled) {
        // User closed or cancelled native dialog
      } else {
        // Native OS picker unavailable on this system or failed -> open integrated file explorer
        console.warn("Native file dialog unavailable, opening in-app file browser:", data.error);
        openFileBrowserModal(target);
      }
    } catch (err) {
      console.warn("Failed to open native file dialog, falling back to in-app file browser:", err);
      openFileBrowserModal(target);
    } finally {
      if (btnBrowseFiles) {
        btnBrowseFiles.disabled = false;
        btnBrowseFiles.innerHTML = originalBrowseHtml || `
          <svg viewBox="0 0 24 24" width="15" height="15" stroke="currentColor" stroke-width="2.2" fill="none">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
          </svg>
          <span>Browse...</span>`;
      }
    }
  }

  // Bind browser triggers
  if (btnBrowseFiles) {
    btnBrowseFiles.addEventListener("click", () => openNativeFileDialog());
  }

  if (videoPathInput) {
    videoPathInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        const p = videoPathInput.value.trim();
        if (p) loadVideoInfo(p);
      }
    });

    videoPathInput.addEventListener("change", () => {
      const p = videoPathInput.value.trim();
      if (p && p !== state.videoPath) {
        loadVideoInfo(p);
      }
    });
  }

  async function loadVideoInfo(path) {
    if (!path) return;
    try {
      metaRes.textContent = "Loading video info...";
      const res = await fetch("/api/video-info", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_path: path })
      });
      if (!res.ok) {
        throw new Error(`Failed to load video: ${res.statusText}`);
      }
      const data = await res.json();
      state.videoPath = data.path;
      if (videoPathInput) videoPathInput.value = data.path;
      state.videoMeta = data.meta;
      state.hasLoadedVideo = true;
      updateStageVisibility();
      
      // Update frame and badges
      stagePoster.src = data.preview_frame_url + "?t=" + Date.now();
      metaRes.textContent = `Resolution: ${data.meta.width} × ${data.meta.height} (${data.meta.is_vertical ? '9:16' : '16:9'})`;
      metaDuration.textContent = `Duration: ${Math.round(data.meta.duration)}s`;

      // Configure timeline scrubber and scene snapshots
      const durationSec = (data.meta && data.meta.duration) ? Number(data.meta.duration) : 0;
      if (stageTimelineSlider) {
        stageTimelineSlider.disabled = false;
        stageTimelineSlider.min = "0";
        stageTimelineSlider.max = String(durationSec || 100);
        stageTimelineSlider.value = "0";
      }
      state.currentSeekTime = 0.0;
      if (timelineCurrentTime) timelineCurrentTime.textContent = "00:00.00";
      if (timelineTotalDuration) timelineTotalDuration.textContent = formatTimestampMMSS(durationSec);
      [btnStepBack5, btnStepBack1, btnStepFwd1, btnStepFwd5].forEach(btn => {
        if (btn) btn.disabled = false;
      });
      renderSceneFilmstrip(data.scene_snapshots);
      renderTimelineKeyframeMarkers();
      updateKeyframeToolbarAndBanner(0.0);

      // Initialize video stream for in-browser playback
      state.isPlaying = false;
      if (typeof fallbackPlaybackTimer !== "undefined" && fallbackPlaybackTimer) {
        clearInterval(fallbackPlaybackTimer);
        fallbackPlaybackTimer = null;
      }
      if (typeof updatePlayPauseUI === "function") updatePlayPauseUI(false);
      const streamToken = state.authToken || (new URLSearchParams(window.location.search)).get("token") || "";
      const streamUrl = `/api/video-stream?path=${encodeURIComponent(data.path)}${streamToken ? `&token=${encodeURIComponent(streamToken)}` : ""}`;
      if (stageVideo) {
        stageVideo.src = streamUrl;
        stageVideo.currentTime = 0;
      }

      // Reset burned video deliverable on new source video load
      state.lastBurnedVideoPath = null;
      state.lastBurnedVideoFilename = null;

      // Update suggested deliverable filename if not customized yet
      if (data.suggested_filename) {
        state.outputFilename = data.suggested_filename;
        if (outputFilenameInput) {
          outputFilenameInput.value = data.suggested_filename;
        }
      }

      // Set aspect ratio of stage
      if (data.meta.width && data.meta.height) {
        videoStage.style.aspectRatio = `${data.meta.width} / ${data.meta.height}`;
      }

      // Check and display sibling .ass and .wav asset detection
      if (data.has_existing_ass) {
        state.hasExistingAss = true;
        state.existingAssPath = data.existing_ass_path;
        state.existingAssName = data.existing_ass_name || (data.existing_ass_path ? data.existing_ass_path.split("/").pop() : null);
        if (badgeExistingAss) {
          badgeExistingAss.classList.remove("hidden");
          if (badgeExistingAssText) {
            badgeExistingAssText.textContent = `✓ Existing subtitles (.ass) found: ${data.existing_ass_name || 'subtitles.ass'} (${data.existing_ass_dialogues || 0} lines)`;
          }
        }
        if (btnBurnOnly) {
          btnBurnOnly.classList.remove("disabled");
          btnBurnOnly.title = "Click to burn existing subtitles into video with GPU NVENC";
        }
        if (titleGenerateAss) titleGenerateAss.textContent = "Re-Transcribe Subtitles (.ass format)";
        if (descGenerateAss) descGenerateAss.textContent = "Generate text from speech. You can edit the transcription in Step 2.";
        if (codeBodyPreview && data.existing_ass_preview) {
          codeBodyPreview.textContent = data.existing_ass_preview;
        }

        if (btnTextDefault) {
          btnTextDefault.disabled = false;
          btnTextDefault.classList.remove("disabled");
          btnTextDefault.title = "Preview subtitle text from dialogue";
        }

        // Auto-load subtitles from disk into the Subtitle File Hub
        refreshAssFileInfo({
          filePath: data.existing_ass_path,
          mediaPath: path
        });
      } else {
        state.hasExistingAss = false;
        state.existingAssPath = null;
        state.existingAssName = null;
        if (badgeExistingAss) badgeExistingAss.classList.add("hidden");
        if (btnBurnOnly) {
          btnBurnOnly.classList.add("disabled");
          btnBurnOnly.title = "Generate or load subtitles first";
        }
        if (titleGenerateAss) titleGenerateAss.textContent = "Generate Subtitles (.ass format)";
        if (descGenerateAss) descGenerateAss.textContent = "Generate text from speech. Open in editor or file manager in Step 2.";
        updateWorkflowStepper('idle');
      }

      syncDeliverableFilenames();

      if (!data.has_existing_ass) {
        // As there is no .ass created from audio yet, display "lorem ipsum" text with animated highlighting
        state.previewText = "Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt.";
        if (previewTextInput) previewTextInput.value = state.previewText;
        if (btnTextLorem) btnTextLorem.classList.add("active");
        if (btnTextDefault) {
          btnTextDefault.disabled = true;
          btnTextDefault.classList.add("disabled");
          btnTextDefault.classList.remove("active");
          btnTextDefault.title = "Transcript unavailable. Generate subtitles (.ass) first in Step 1.";
        }
        state.activeWordIndex = 0;
        renderSubtitlePreview();

        // Reset Subtitle File Hub
        updateAssHubUIEmpty();
      }

      if (data.has_existing_wav) {
        state.hasExistingWav = true;
        state.existingWavPath = data.existing_wav_path;
        if (badgeExistingWav) {
          badgeExistingWav.classList.remove("hidden");
          if (badgeExistingWavText) {
            badgeExistingWavText.textContent = `✓ Existing audio (.wav) found: ${data.existing_wav_name || 'audio.wav'}`;
          }
        }
      } else {
        state.hasExistingWav = false;
        state.existingWavPath = null;
        if (badgeExistingWav) badgeExistingWav.classList.add("hidden");
      }
    } catch (err) {
      console.warn("Could not load video preview frame automatically:", err);
      metaRes.textContent = "Custom Video File";
    }
  }

  // ----------------------------------------------------
  // 2. Position Updates & Drag-and-Drop
  // ----------------------------------------------------
  function updatePosition(x, y, updateSliders = true) {
    state.posX = Math.max(10, Math.min(90, Math.round(x)));
    state.posY = Math.max(15, Math.min(92, Math.round(y)));

    subtitleDragBox.style.left = `${state.posX}%`;
    subtitleDragBox.style.top = `${state.posY}%`;

    if (updateSliders) {
      sliderPosX.value = state.posX;
      sliderPosY.value = state.posY;
      labelPosX.textContent = `${state.posX}%`;
      labelPosY.textContent = `${state.posY}%`;
    }
    updateBoundsEnvelope();
    if (state.isAtKeyframe) {
      syncActiveKeyframeFromState();
    }
  }

  function updateBoundsEnvelope() {
    if (!subtitleBoundsEnvelope) return;
    if (!state.showBounds || !state.hasLoadedVideo) {
      subtitleBoundsEnvelope.classList.add("hidden");
      if (btnToggleBounds) btnToggleBounds.classList.remove("active");
      return;
    }

    subtitleBoundsEnvelope.classList.remove("hidden");
    if (btnToggleBounds) btnToggleBounds.classList.add("active");

    // Position matches subtitleDragBox coordinates
    subtitleBoundsEnvelope.style.left = `${state.posX}%`;
    subtitleBoundsEnvelope.style.top = `${state.posY}%`;

    // Maximum width matches user's Line Width / Subtitle Box Width setting
    subtitleBoundsEnvelope.style.width = `${state.lineWidthPct}%`;

    // Base font size in preview (scaled proportional to preview height ~500px vs 1920px video)
    const scaleRatio = 0.28;
    const renderedFontSize = Math.round((state.fontSize || 68) * scaleRatio);
    const lineHeightPx = renderedFontSize * 1.34;
    const lines = Math.max(1, Math.min(3, state.maxLines || 1));

    // Calculate boost headroom for highlighted word scale
    const boostScale = (state.highlightScalePct || 100) / 100;
    const boostHeadroom = Math.round(renderedFontSize * Math.max(0, boostScale - 1.0));

    // Box padding if block pill or standard text padding
    const isBox = (state.highlightStyle === "box");
    const boxPadding = isBox ? 28 : 16;

    const totalHeight = Math.round((lines * lineHeightPx) + boostHeadroom + boxPadding);
    subtitleBoundsEnvelope.style.height = `${totalHeight}px`;

    // Update live badge text
    if (boundsBadge) {
      const boostText = state.highlightScalePct > 100 ? ` • Boost ${state.highlightScalePct}%` : "";
      boundsBadge.textContent = `Bounds: ${state.lineWidthPct}% W • ${lines} ${lines === 1 ? 'Line' : 'Lines'} • Max ${state.maxChars} Chars${boostText}`;
    }

    // Render guide lines inside envelope
    if (boundsGuidelines) {
      let guidesHtml = "";
      for (let i = 1; i <= lines; i++) {
        guidesHtml += `<div class="bounds-line-guide"><span class="bounds-line-label">Line ${i}</span></div>`;
      }
      boundsGuidelines.innerHTML = guidesHtml;
    }
  }

  // Drag on preview stage
  let isDragging = false;

  subtitleDragBox.addEventListener("mousedown", (e) => {
    isDragging = true;
    subtitleDragBox.classList.add("dragging");
    e.preventDefault();
  });

  window.addEventListener("mouseup", () => {
    if (isDragging) {
      isDragging = false;
      subtitleDragBox.classList.remove("dragging");
    }
  });

  window.addEventListener("mousemove", (e) => {
    if (!isDragging) return;
    const rect = videoStage.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    let pctX = (mouseX / rect.width) * 100;
    let pctY = (mouseY / rect.height) * 100;

    // Center snap tolerance (50%)
    if (Math.abs(pctX - 50) < 3.5) {
      pctX = 50;
    }

    updatePosition(pctX, pctY, true);
  });

  // Touch support for dragging
  subtitleDragBox.addEventListener("touchstart", (e) => {
    isDragging = true;
    subtitleDragBox.classList.add("dragging");
  }, { passive: true });

  window.addEventListener("touchend", () => {
    isDragging = false;
    subtitleDragBox.classList.remove("dragging");
  });

  window.addEventListener("touchmove", (e) => {
    if (!isDragging || !e.touches[0]) return;
    const rect = videoStage.getBoundingClientRect();
    const touch = e.touches[0];
    const mouseX = touch.clientX - rect.left;
    const mouseY = touch.clientY - rect.top;

    let pctX = (mouseX / rect.width) * 100;
    let pctY = (mouseY / rect.height) * 100;

    if (Math.abs(pctX - 50) < 3.5) pctX = 50;
    updatePosition(pctX, pctY, true);
  }, { passive: true });

  // Slider events
  sliderPosY.addEventListener("input", (e) => {
    labelPosY.textContent = `${e.target.value}%`;
    updatePosition(state.posX, parseFloat(e.target.value), false);
  });

  sliderPosX.addEventListener("input", (e) => {
    labelPosX.textContent = `${e.target.value}%`;
    updatePosition(parseFloat(e.target.value), state.posY, false);
  });

  // Preset Buttons
  presetBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      presetBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const y = parseFloat(btn.dataset.y);
      const x = parseFloat(btn.dataset.x);
      updatePosition(x, y, true);
    });
  });

  btnResetPos.addEventListener("click", () => {
    updatePosition(50, 78, true);
  });

  // ----------------------------------------------------
  // 2b. Timeline Frame Scrubber & Scene Jump Tray
  // ----------------------------------------------------
  function formatTimestampMMSS(sec) {
    if (!sec || isNaN(sec) || sec < 0) return "00:00.00";
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    const ms = Math.floor((sec % 1) * 100);
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${String(ms).padStart(2, "0")}`;
  }

  function parseAssTimestamp(tsStr) {
    if (!tsStr || typeof tsStr !== "string") return 0;
    const parts = tsStr.trim().split(":");
    if (parts.length === 3) {
      const h = parseFloat(parts[0]) || 0;
      const m = parseFloat(parts[1]) || 0;
      const s = parseFloat(parts[2]) || 0;
      return h * 3600 + m * 60 + s;
    } else if (parts.length === 2) {
      const m = parseFloat(parts[0]) || 0;
      const s = parseFloat(parts[1]) || 0;
      return m * 60 + s;
    }
    return parseFloat(tsStr) || 0;
  }

  function updatePlayPauseUI(isPlaying) {
    if (!btnPlayPause) return;
    if (isPlaying) {
      btnPlayPause.classList.add("playing");
      if (playIcon) playIcon.textContent = "⏸";
      if (playLabel) playLabel.textContent = "Pause";
      btnPlayPause.title = "Pause playback (Space)";
      btnPlayPause.setAttribute("aria-label", "Pause video");
    } else {
      btnPlayPause.classList.remove("playing");
      if (playIcon) playIcon.textContent = "▶";
      if (playLabel) playLabel.textContent = "Play";
      btnPlayPause.title = "Play video from current playhead position (Space)";
      btnPlayPause.setAttribute("aria-label", "Play video");
    }
  }

  let fallbackPlaybackTimer = null;
  function startFallbackPlayback(startT, dur) {
    state.isPlaying = true;
    updatePlayPauseUI(true);
    let t = startT;
    const step = 0.1;
    if (fallbackPlaybackTimer) clearInterval(fallbackPlaybackTimer);
    fallbackPlaybackTimer = setInterval(() => {
      t += step;
      if (t >= dur) {
        t = dur;
        togglePlayPause(false);
      }
      seekVideoStageTo(t, true, true);
    }, 100);
  }

  function togglePlayPause(forceState = null) {
    if (!state.hasLoadedVideo || !state.videoPath) return;

    const shouldPlay = (forceState !== null) ? forceState : !state.isPlaying;

    if (shouldPlay) {
      const token = state.authToken || (new URLSearchParams(window.location.search)).get("token") || "";
      const streamUrl = `/api/video-stream?path=${encodeURIComponent(state.videoPath)}${token ? `&token=${encodeURIComponent(token)}` : ""}`;

      if (stageVideo && (!stageVideo.src || !stageVideo.src.includes(encodeURIComponent(state.videoPath)))) {
        stageVideo.src = streamUrl;
      }

      const dur = (state.videoMeta && state.videoMeta.duration) ? Number(state.videoMeta.duration) : 100;
      let startT = state.currentSeekTime || 0;
      if (startT >= dur - 0.2) {
        startT = 0; // Loop around if playhead was at the end
      }

      if (stageVideo) {
        stageVideo.currentTime = startT;
        stageVideo.play().then(() => {
          state.isPlaying = true;
          if (stagePoster) stagePoster.classList.add("hidden");
          stageVideo.classList.remove("hidden");
          updatePlayPauseUI(true);
        }).catch(err => {
          console.warn("Direct HTML5 video play failed, falling back to simulated timeline playback:", err);
          startFallbackPlayback(startT, dur);
        });
      } else {
        startFallbackPlayback(startT, dur);
      }
    } else {
      if (fallbackPlaybackTimer) {
        clearInterval(fallbackPlaybackTimer);
        fallbackPlaybackTimer = null;
      }
      if (stageVideo) {
        stageVideo.pause();
      }
      state.isPlaying = false;
      updatePlayPauseUI(false);
    }
  }

  // ----------------------------------------------------
  // 2c. Timeline Keyframe Management & Style Scoping
  // ----------------------------------------------------

  /**
   * Find the keyframe that takes effect at timestamp t.
   * CRITICAL REQUIREMENT: The style defined by a keyframe stays in effect
   * to the right of the timeline until another keyframe is encountered.
   * If t is before the first keyframe, returns null (base preset applies).
   */
  function findActiveKeyframe(t) {
    if (!state.keyframes || state.keyframes.length === 0) return null;
    let active = null;
    for (const kf of state.keyframes) {
      if (Number(kf.time) <= t + 0.05) {
        active = kf;
      } else {
        break;
      }
    }
    return active;
  }

  /**
   * Check if playhead is snapped on or near an existing keyframe within tolerance.
   */
  function findKeyframeAtTime(t, tolerance = 0.25) {
    if (!state.keyframes || state.keyframes.length === 0) return null;
    for (const kf of state.keyframes) {
      if (Math.abs(Number(kf.time) - t) <= tolerance) {
        return kf;
      }
    }
    return null;
  }

  function renderTimelineKeyframeMarkers() {
    if (!timelineKeyframesTrack) return;
    timelineKeyframesTrack.innerHTML = "";
    const dur = (state.videoMeta && state.videoMeta.duration) ? Number(state.videoMeta.duration) : 100;
    if (!dur || dur <= 0 || !Array.isArray(state.keyframes) || state.keyframes.length === 0) {
      if (keyframeCountBadge) keyframeCountBadge.style.display = "none";
      if (btnPrevKeyframe) btnPrevKeyframe.disabled = true;
      if (btnNextKeyframe) btnNextKeyframe.disabled = true;
      return;
    }

    if (keyframeCountBadge) {
      keyframeCountBadge.textContent = `${state.keyframes.length} Keyframe${state.keyframes.length === 1 ? "" : "s"}`;
      keyframeCountBadge.style.display = "inline-block";
    }

    const currentT = state.currentSeekTime || 0;
    const hasPrev = state.keyframes.some(kf => Number(kf.time) < currentT - 0.1);
    const hasNext = state.keyframes.some(kf => Number(kf.time) > currentT + 0.1);
    if (btnPrevKeyframe) btnPrevKeyframe.disabled = !hasPrev;
    if (btnNextKeyframe) btnNextKeyframe.disabled = !hasNext;

    state.keyframes.forEach(kf => {
      const marker = document.createElement("button");
      marker.type = "button";
      marker.className = "keyframe-marker";
      marker.dataset.keyframeId = String(kf.id);
      marker.dataset.time = String(kf.time);

      const pct = Math.max(0, Math.min(100, (Number(kf.time) / dur) * 100));
      marker.style.left = `${pct.toFixed(2)}%`;

      const timeFmt = formatTimestampMMSS(Number(kf.time));
      const kfFont = (kf.styling && (kf.styling.fontFamily || kf.styling.font_name)) || state.fontFamily || "Montserrat";
      const kfSize = (kf.styling && (kf.styling.fontSize || kf.styling.font_size)) || state.fontSize || 68;
      marker.title = `Keyframe at ${timeFmt} (${kfFont}, ${kfSize}px) - Click to jump`;
      marker.setAttribute("aria-label", `Keyframe at ${timeFmt}`);

      const isActive = (state.activeKeyframeId === kf.id) || (Math.abs(Number(kf.time) - currentT) <= 0.25);
      if (isActive) {
        marker.classList.add("active");
      }

      marker.addEventListener("click", (e) => {
        e.stopPropagation();
        seekVideoStageTo(Number(kf.time), true);
      });

      timelineKeyframesTrack.appendChild(marker);
    });
  }

  function updateKeyframeToolbarAndBanner(t) {
    const dur = (state.videoMeta && state.videoMeta.duration) ? Number(state.videoMeta.duration) : 100;
    const clamped = Math.max(0, Math.min(Number(t) || 0, dur));

    const snapped = findKeyframeAtTime(clamped, 0.25);
    state.isAtKeyframe = Boolean(snapped);
    state.selectedKeyframeId = snapped ? snapped.id : null;

    if (snapped) {
      if (btnDeleteKeyframe) {
        btnDeleteKeyframe.disabled = false;
        btnDeleteKeyframe.title = `Delete keyframe at ${formatTimestampMMSS(snapped.time)}`;
      }
      if (btnAddKeyframe) {
        btnAddKeyframe.textContent = "🔄 Update KF";
        btnAddKeyframe.title = `Update styling of keyframe at ${formatTimestampMMSS(snapped.time)}`;
      }
    } else {
      if (btnDeleteKeyframe) {
        btnDeleteKeyframe.disabled = true;
        btnDeleteKeyframe.title = "No keyframe at current playhead position to delete";
      }
      if (btnAddKeyframe) {
        btnAddKeyframe.textContent = "➕ Keyframe";
        btnAddKeyframe.title = "Add a new styling keyframe at current playhead position";
        btnAddKeyframe.disabled = !state.hasLoadedVideo;
      }
    }

    const activeKf = findActiveKeyframe(clamped);
    state.activeKeyframeId = activeKf ? activeKf.id : null;

    if (activeKf) {
      if (timelineKeyframeBanner) timelineKeyframeBanner.style.display = "flex";
      if (keyframeBannerText) {
        const kfIndex = state.keyframes.findIndex(k => k.id === activeKf.id) + 1;
        const fontName = (activeKf.styling && (activeKf.styling.fontFamily || activeKf.styling.font_name)) || state.fontFamily;
        const fontSize = (activeKf.styling && (activeKf.styling.fontSize || activeKf.styling.font_size)) || state.fontSize;
        keyframeBannerText.textContent = `💎 Keyframe ${kfIndex}/${state.keyframes.length} @ ${formatTimestampMMSS(activeKf.time)} (${fontName}, ${fontSize}px)`;
      }
      if (keyframeBannerHint) {
        if (snapped) {
          keyframeBannerHint.textContent = "Active keyframe playhead. Styling changes directly update this keyframe.";
        } else {
          keyframeBannerHint.textContent = "Style stays in effect to the right of the timeline until next keyframe.";
        }
      }
    } else if (state.keyframes && state.keyframes.length > 0) {
      if (timelineKeyframeBanner) timelineKeyframeBanner.style.display = "flex";
      if (keyframeBannerText) {
        keyframeBannerText.textContent = "Base Style (Prior to first keyframe)";
      }
      if (keyframeBannerHint) {
        keyframeBannerHint.textContent = `First keyframe starts at ${formatTimestampMMSS(state.keyframes[0].time)}.`;
      }
    } else {
      if (timelineKeyframeBanner) timelineKeyframeBanner.style.display = "none";
    }

    // Refresh marker active states
    if (timelineKeyframesTrack) {
      const markers = timelineKeyframesTrack.querySelectorAll(".keyframe-marker");
      markers.forEach(m => {
        const mTime = Number(m.dataset.time);
        const isActive = activeKf && (m.dataset.keyframeId === activeKf.id || Math.abs(mTime - clamped) <= 0.25);
        m.classList.toggle("active", Boolean(isActive));
      });
    }

    // Update prev/next jump buttons
    if (btnPrevKeyframe && btnNextKeyframe && state.keyframes) {
      btnPrevKeyframe.disabled = !state.keyframes.some(kf => Number(kf.time) < clamped - 0.1);
      btnNextKeyframe.disabled = !state.keyframes.some(kf => Number(kf.time) > clamped + 0.1);
    }
  }

  function syncActiveKeyframeFromState() {
    if (!state.isAtKeyframe || !state.selectedKeyframeId || !state.keyframes) return;
    const kf = state.keyframes.find(k => k.id === state.selectedKeyframeId);
    if (kf) {
      kf.styling = getCurrentStylingSnapshot(false);
    }
  }

  function addOrUpdateKeyframeAtCurrentTime() {
    if (!state.hasLoadedVideo) return;
    const t = state.currentSeekTime || 0;
    const snapshot = getCurrentStylingSnapshot(false);
    const existing = findKeyframeAtTime(t, 0.25);

    if (existing) {
      existing.styling = snapshot;
      existing.label = `Keyframe @ ${formatTimestampMMSS(existing.time)}`;
      showPresetStatus(`Updated keyframe styling at ${formatTimestampMMSS(existing.time)}`);
    } else {
      const newKf = {
        id: "kf_" + Date.now() + "_" + Math.floor(Math.random() * 1000),
        time: Number(t.toFixed(2)),
        label: `Keyframe @ ${formatTimestampMMSS(t)}`,
        styling: snapshot
      };
      state.keyframes.push(newKf);
      state.keyframes.sort((a, b) => Number(a.time) - Number(b.time));
      showPresetStatus(`Added keyframe at ${formatTimestampMMSS(t)} (style active to the right)`);
    }

    updatePresetToolbarState();
    renderTimelineKeyframeMarkers();
    updateKeyframeToolbarAndBanner(t);
  }

  function deleteKeyframeAtCurrentTime() {
    if (!state.hasLoadedVideo || !state.keyframes || state.keyframes.length === 0) return;
    const t = state.currentSeekTime || 0;
    const existing = findKeyframeAtTime(t, 0.25);
    if (!existing) return;

    state.keyframes = state.keyframes.filter(k => k.id !== existing.id);
    showPresetStatus(`Deleted keyframe at ${formatTimestampMMSS(existing.time)}`);

    updatePresetToolbarState();
    renderTimelineKeyframeMarkers();
    seekVideoStageTo(t, false);
  }

  function jumpToPrevKeyframe() {
    if (!state.keyframes || state.keyframes.length === 0) return;
    const currentT = state.currentSeekTime || 0;
    const candidates = state.keyframes.filter(kf => Number(kf.time) < currentT - 0.08);
    if (candidates.length > 0) {
      const prevKf = candidates[candidates.length - 1];
      seekVideoStageTo(Number(prevKf.time), true);
    }
  }

  function jumpToNextKeyframe() {
    if (!state.keyframes || state.keyframes.length === 0) return;
    const currentT = state.currentSeekTime || 0;
    const candidates = state.keyframes.filter(kf => Number(kf.time) > currentT + 0.08);
    if (candidates.length > 0) {
      const nextKf = candidates[0];
      seekVideoStageTo(Number(nextKf.time), true);
    }
  }

  let seekDebounceTimer = null;
  function seekVideoStageTo(timestampSec, updateSlider = true, fromVideoPlayback = false) {
    if (!state.hasLoadedVideo || !state.videoPath) return;
    const dur = (state.videoMeta && state.videoMeta.duration) ? Number(state.videoMeta.duration) : 100;
    const clamped = Math.max(0, Math.min(Number(timestampSec) || 0, dur));
    state.currentSeekTime = clamped;

    if (updateSlider && stageTimelineSlider) {
      stageTimelineSlider.value = String(clamped);
    }
    if (timelineCurrentTime) {
      timelineCurrentTime.textContent = formatTimestampMMSS(clamped);
    }

    if (!fromVideoPlayback && stageVideo && stageVideo.src) {
      if (Math.abs(stageVideo.currentTime - clamped) > 0.12) {
        stageVideo.currentTime = clamped;
      }
    }

    // Evaluate active keyframe at this timestamp.
    // The style stays in effect to the right of the timeline until another keyframe is encountered.
    const activeKf = findActiveKeyframe(clamped);
    if (activeKf) {
      if (activeKf.id !== state.activeKeyframeId) {
        state.activeKeyframeId = activeKf.id;
        applyPresetStyling(activeKf.styling, true);
      }
    } else if (state.activeKeyframeId !== null) {
      // Revert to base preset styling when scrubbing prior to the first keyframe
      state.activeKeyframeId = null;
      if (state.basePresetStyling) {
        applyPresetStyling(state.basePresetStyling, true);
      }
    }

    updateKeyframeToolbarAndBanner(clamped);

    // If dialogue lines exist, sync dialogue text at current playback timestamp
    if (state.dialogues && state.dialogues.length > 0) {
      const activeLine = state.dialogues.find(dl => {
        const s = parseAssTimestamp(dl.start);
        const e = parseAssTimestamp(dl.end);
        return clamped >= s && clamped <= e;
      });
      if (activeLine && activeLine.clean_text && activeLine.clean_text !== state.currentDialogueLineText) {
        state.currentDialogueLineText = activeLine.clean_text;
        state.previewText = activeLine.clean_text;
        if (previewTextInput) previewTextInput.value = activeLine.clean_text;
        renderSubtitlePreview();
      }
    }

    // Highlight closest scene card in filmstrip tray
    if (sceneFilmstripTray) {
      const cards = sceneFilmstripTray.querySelectorAll(".scene-filmstrip-card");
      let closestCard = null;
      let minDiff = 2.0;
      cards.forEach(card => {
        card.classList.remove("active");
        const cardTs = Number(card.dataset.timestamp);
        const diff = Math.abs(cardTs - clamped);
        if (diff < minDiff) {
          minDiff = diff;
          closestCard = card;
        }
      });
      if (closestCard) {
        closestCard.classList.add("active");
      }
    }

    if (!fromVideoPlayback) {
      if (seekDebounceTimer) clearTimeout(seekDebounceTimer);
      seekDebounceTimer = setTimeout(() => {
        if (!state.videoPath || !stagePoster) return;
        stagePoster.src = `/api/video-frame?path=${encodeURIComponent(state.videoPath)}&t=${clamped.toFixed(2)}`;
      }, 40);
    }
  }

  function renderSceneFilmstrip(snapshots) {
    if (!sceneFilmstripTray) return;
    sceneFilmstripTray.innerHTML = "";
    if (!Array.isArray(snapshots) || !snapshots.length) {
      sceneFilmstripTray.innerHTML = '<span class="timeline-empty-hint" style="font-size: 0.74rem; color: var(--text-muted, #94a3b8); font-style: italic; grid-column: span 5; text-align: center; padding: 6px;">No scene snapshots available.</span>';
      return;
    }

    snapshots.forEach((snap, idx) => {
      const card = document.createElement("div");
      card.className = "scene-filmstrip-card";
      if (idx === 0) card.classList.add("active");
      card.dataset.timestamp = String(snap.timestamp);
      card.title = `Jump to ${snap.label} (${formatTimestampMMSS(snap.timestamp)})`;

      const img = document.createElement("img");
      img.className = "scene-filmstrip-img";
      img.src = snap.url;
      img.alt = `Scene at ${snap.label}`;
      img.loading = "lazy";

      const label = document.createElement("span");
      label.className = "scene-filmstrip-label";
      label.textContent = `${snap.label} (${formatTimestampMMSS(snap.timestamp)})`;

      card.appendChild(img);
      card.appendChild(label);

      card.addEventListener("click", () => {
        seekVideoStageTo(snap.timestamp, true);
      });

      sceneFilmstripTray.appendChild(card);
    });
  }

  if (stageTimelineSlider) {
    stageTimelineSlider.addEventListener("input", (e) => {
      seekVideoStageTo(Number(e.target.value), false, false);
    });
    stageTimelineSlider.addEventListener("change", (e) => {
      seekVideoStageTo(Number(e.target.value), true, false);
    });
  }

  // Play / Pause Button Listener
  if (btnPlayPause) {
    btnPlayPause.addEventListener("click", () => {
      togglePlayPause();
    });
  }

  // HTML5 Video Playback Events
  if (stageVideo) {
    stageVideo.addEventListener("play", () => {
      state.isPlaying = true;
      if (stagePoster) stagePoster.classList.add("hidden");
      stageVideo.classList.remove("hidden");
      updatePlayPauseUI(true);
    });
    stageVideo.addEventListener("pause", () => {
      state.isPlaying = false;
      updatePlayPauseUI(false);
    });
    stageVideo.addEventListener("ended", () => {
      state.isPlaying = false;
      updatePlayPauseUI(false);
    });
    stageVideo.addEventListener("timeupdate", () => {
      if (!state.isPlaying) return;
      seekVideoStageTo(stageVideo.currentTime, true, true);
    });
  }

  // Click on video stage background to toggle play/pause
  if (videoStage) {
    videoStage.addEventListener("click", (e) => {
      if (e.target.closest("#subtitleDragBox") || e.target.closest(".keyframe-marker") || e.target.closest("button")) {
        return;
      }
      if (state.hasLoadedVideo) {
        togglePlayPause();
      }
    });
  }

  // Keyboard shortcut: Spacebar to toggle Play/Pause when media is loaded
  window.addEventListener("keydown", (e) => {
    if (e.code === "Space" || e.key === " ") {
      const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : "";
      if (activeTag === "input" || activeTag === "textarea" || activeTag === "select") {
        return;
      }
      if (state.hasLoadedVideo) {
        e.preventDefault();
        togglePlayPause();
      }
    }
  });

  if (btnAddKeyframe) {
    btnAddKeyframe.addEventListener("click", () => {
      addOrUpdateKeyframeAtCurrentTime();
    });
  }

  if (btnDeleteKeyframe) {
    btnDeleteKeyframe.addEventListener("click", () => {
      deleteKeyframeAtCurrentTime();
    });
  }

  if (btnPrevKeyframe) {
    btnPrevKeyframe.addEventListener("click", () => {
      jumpToPrevKeyframe();
    });
  }

  if (btnNextKeyframe) {
    btnNextKeyframe.addEventListener("click", () => {
      jumpToNextKeyframe();
    });
  }

  if (btnStepBack5) {
    btnStepBack5.addEventListener("click", () => {
      seekVideoStageTo((state.currentSeekTime || 0) - 5, true);
    });
  }
  if (btnStepBack1) {
    btnStepBack1.addEventListener("click", () => {
      seekVideoStageTo((state.currentSeekTime || 0) - 1, true);
    });
  }
  if (btnStepFwd1) {
    btnStepFwd1.addEventListener("click", () => {
      seekVideoStageTo((state.currentSeekTime || 0) + 1, true);
    });
  }
  if (btnStepFwd5) {
    btnStepFwd5.addEventListener("click", () => {
      seekVideoStageTo((state.currentSeekTime || 0) + 5, true);
    });
  }

  // ----------------------------------------------------
  // 3. Styling & Live Preview Rendering
  // ----------------------------------------------------
  function renderSubtitlePreview() {
    if (state.isAtKeyframe && state.stylingModified) {
      syncActiveKeyframeFromState();
    }

    // 1. Text styling
    const font = state.fontFamily;
    const weight = state.bold ? "700" : "400";
    const style = state.italic ? "italic" : "normal";
    const outlineW = state.outlineWidth;
    const outlineC = state.outlineColor;
    const baseC = state.textBaseColor;

    subtitleRenderedText.style.fontFamily = `"${font}", sans-serif`;
    subtitleRenderedText.style.fontWeight = weight;
    subtitleRenderedText.style.fontStyle = style;
    subtitleRenderedText.style.color = baseC;

    // Scale font size proportionally to preview box height (~500px vs 1920px video)
    const scaleRatio = 0.28;
    subtitleRenderedText.style.fontSize = `${Math.round(state.fontSize * scaleRatio)}px`;

    // Construct text shadow outline
    if (outlineW > 0) {
      const o = outlineW * scaleRatio;
      subtitleRenderedText.style.textShadow = `
        -${o}px -${o}px 0 ${outlineC},
         ${o}px -${o}px 0 ${outlineC},
        -${o}px  ${o}px 0 ${outlineC},
         ${o}px  ${o}px 0 ${outlineC}
      `;
    } else {
      subtitleRenderedText.style.textShadow = "none";
    }

    // Line Block Box styling if applicable
    if (state.highlightStyle === "box" && state.boxType === "block") {
      const alphaHex = Math.round(state.boxOpacity * 255).toString(16).padStart(2, '0');
      subtitleRenderedText.style.background = `${state.boxBgColor}${alphaHex}`;
      subtitleRenderedText.style.padding = "6px 14px";
      subtitleRenderedText.style.borderRadius = "8px";
    } else {
      subtitleRenderedText.style.background = "transparent";
      subtitleRenderedText.style.padding = "0";
      subtitleRenderedText.style.borderRadius = "0";
    }

    // Set subtitle drag box width based on user line width setting
    subtitleDragBox.style.width = `${state.lineWidthPct}%`;
    subtitleDragBox.style.maxWidth = `${state.lineWidthPct}%`;

    // 2. Format words into lines according to maxLines, maxChars, and lineWidthPct
    const cleanedPreview = (state.previewText || "")
      .replace(/\\N/gi, " ")
      .replace(/\\h/gi, " ")
      .replace(/\s+/g, " ")
      .trim();
    const words = cleanedPreview ? cleanedPreview.split(/\s+/) : [];
    if (words.length === 0) return;

    // Calculate effective character budget based on selected line width percentage
    const widthCharBudget = Math.max(12, Math.floor((state.lineWidthPct / 100) * 35));
    const effectiveMaxChars = Math.min(state.maxChars, widthCharBudget);

    // 2. Chunk preview text into discrete blocks of maxLines (Option A)
    const blocks = [];
    let currentBlock = [];
    let currentLine = [];
    let currentLen = 0;

    for (const w of words) {
      if (currentLen + w.length + (currentLen > 0 ? 1 : 0) > effectiveMaxChars && currentLine.length > 0) {
        currentBlock.push(currentLine);
        currentLine = [];
        currentLen = 0;
        if (currentBlock.length >= state.maxLines) {
          blocks.push(currentBlock);
          currentBlock = [];
        }
      }
      currentLine.push(w);
      currentLen += w.length + 1;
    }
    if (currentLine.length > 0) {
      currentBlock.push(currentLine);
    }
    if (currentBlock.length > 0) {
      blocks.push(currentBlock);
    }
    if (blocks.length === 0) return;

    // Total words across the preview text
    const totalWords = words.length;
    if (state.activeWordIndex >= totalWords) {
      state.activeWordIndex = 0;
    }

    // Determine which block is currently active
    let wordCounter = 0;
    let activeBlock = blocks[0];
    let activeWordIndexInBlock = 0;

    for (const b of blocks) {
      const bWordsCount = b.flat().length;
      if (state.activeWordIndex >= wordCounter && state.activeWordIndex < wordCounter + bWordsCount) {
        activeBlock = b;
        activeWordIndexInBlock = state.activeWordIndex - wordCounter;
        break;
      }
      wordCounter += bWordsCount;
    }

    // Rebuild HTML for ONLY the active block (immediately erasing any previous block/line)
    let blockWordIdx = 0;
    const htmlLines = activeBlock.map((line, lineIdx) => {
      // Per-speaker styling when multi-speaker mode is active
      let spkChannel = null;
      if (state.isMultiSpeaker && state.speakerChannels) {
        const spkKeys = Object.keys(state.speakerChannels).slice(0, state.speakerCount);
        if (spkKeys.length >= 2) {
          const spkKey = (activeBlock.length === 1 && state.activeSpeakerId && spkKeys.includes(state.activeSpeakerId))
            ? state.activeSpeakerId
            : spkKeys[lineIdx % spkKeys.length];
          spkChannel = state.speakerChannels[spkKey];
        }
      }

      const activeHighlight = (spkChannel && spkChannel.highlight_color) ? spkChannel.highlight_color : state.highlightColor;
      const activePrimary = (spkChannel && spkChannel.primary_color) ? spkChannel.primary_color : baseC;
      const activeBoxBg = (spkChannel && spkChannel.box_bg_color) ? spkChannel.box_bg_color : state.boxBgColor;
      const activeBoxFont = (spkChannel && spkChannel.box_font_color) ? spkChannel.box_font_color : state.boxFontColor;

      const lineHtml = line.map(w => {
        const isActive = (blockWordIdx === activeWordIndexInBlock);
        const isNext = (state.highlightAnimation === "anticipation_glow" && blockWordIdx === activeWordIndexInBlock + 1);
        blockWordIdx++;

        let extraClass = "";
        let inlineStyle = "";

        if (isActive) {
          const scale = state.highlightScalePct / 100;
          const scaleTransform = `transform: scale(${scale}); transform-origin: center bottom; display: inline-block;`;
          const marginSpacing = (state.highlightScalePct > 100)
            ? `margin: 0 ${Math.max(2.5, (state.highlightScalePct - 100) * 0.12)}px;`
            : "";

          if (state.highlightAnimation === "karaoke_wipe") {
            extraClass = "active-color active-wipe";
            inlineStyle = `color: ${activeHighlight} !important; border-bottom: 2px solid ${activeHighlight}; ${scaleTransform} ${marginSpacing}`;
          } else if (state.highlightStyle === "color") {
            extraClass = "active-color";
            inlineStyle = `color: ${activeHighlight} !important; ${scaleTransform} ${marginSpacing}`;
          } else if (state.highlightStyle === "box") {
            if (state.boxType === "word") {
              extraClass = "active-pill";
              const alphaHex = Math.round(state.boxOpacity * 255).toString(16).padStart(2, '0');
              inlineStyle = `background: ${activeBoxBg}${alphaHex} !important; color: ${activeBoxFont} !important; border-color: ${activeBoxBg} !important; ${scaleTransform} ${marginSpacing}`;
            } else {
              // Block line box: active word font changes color
              inlineStyle = `color: ${activeHighlight} !important; ${scaleTransform} ${marginSpacing}`;
            }
          }
        } else if (isNext) {
          inlineStyle = `color: ${activePrimary}; text-shadow: 0 0 8px ${activeHighlight}, 0 0 12px ${activeHighlight};`;
        } else if (spkChannel) {
          inlineStyle = `color: ${activePrimary};`;
        }

        return `<span class="subtitle-word ${extraClass}" style="${inlineStyle}">${w}</span>`;
      }).join(" ");

      let speakerPrefix = "";
      if (state.isMultiSpeaker && spkChannel && (state.maxLines > 1 || lineIdx === 0)) {
        speakerPrefix = `<span style="font-size:0.75em; opacity:0.85; margin-right:6px; color:${spkChannel.highlight_color}; font-weight:700;">[${spkChannel.name || 'Speaker'}]:</span>`;
      }

      return `<div>${speakerPrefix}${lineHtml}</div>`;
    });

    subtitleRenderedText.innerHTML = htmlLines.join("");
    updateBoundsEnvelope();
  }

  // Animated Word Highlight Loop (simulates speech word highlight)
  setInterval(() => {
    state.activeWordIndex++;
    renderSubtitlePreview();
  }, 420);

  // ----------------------------------------------------
  // 4. Style Controls Event Listeners
  // ----------------------------------------------------
  selectFontFamily.addEventListener("change", (e) => {
    state.fontFamily = e.target.value;
    state.stylingModified = true;
    renderSubtitlePreview();
  });

  sliderFontSize.addEventListener("input", (e) => {
    state.fontSize = parseInt(e.target.value);
    labelFontSize.textContent = `${state.fontSize} pt`;
    state.stylingModified = true;
    renderSubtitlePreview();
  });

  colorTextBase.addEventListener("input", (e) => {
    state.textBaseColor = e.target.value.toUpperCase();
    codeTextBase.textContent = state.textBaseColor;
    if (state.isMultiSpeaker && state.speakerChannels && state.speakerChannels[state.activeSpeakerId]) {
      state.speakerChannels[state.activeSpeakerId].primary_color = state.textBaseColor;
    }
    state.stylingModified = true;
    renderSubtitlePreview();
  });

  colorOutline.addEventListener("input", (e) => {
    state.outlineColor = e.target.value.toUpperCase();
    codeOutline.textContent = state.outlineColor;
    if (state.isMultiSpeaker && state.speakerChannels && state.speakerChannels[state.activeSpeakerId]) {
      state.speakerChannels[state.activeSpeakerId].outline_color = state.outlineColor;
    }
    state.stylingModified = true;
    renderSubtitlePreview();
  });

  sliderOutlineWidth.addEventListener("input", (e) => {
    state.outlineWidth = parseFloat(e.target.value);
    labelOutlineWidth.textContent = `${state.outlineWidth} px`;
    state.stylingModified = true;
    renderSubtitlePreview();
  });

  checkBold.addEventListener("change", (e) => {
    state.bold = e.target.checked;
    state.stylingModified = true;
    renderSubtitlePreview();
  });

  checkItalic.addEventListener("change", (e) => {
    state.italic = e.target.checked;
    state.stylingModified = true;
    renderSubtitlePreview();
  });

  // Highlight Segment Controls
  btnStyleColor.addEventListener("click", () => {
    state.highlightStyle = "color";
    btnStyleColor.classList.add("active");
    btnStyleBox.classList.remove("active");
    paneHighlightColor.classList.remove("hidden");
    paneHighlightColor.style.display = "";
    paneHighlightBox.classList.add("hidden");
    paneHighlightBox.style.display = "";
    state.stylingModified = true;
    renderSubtitlePreview();
  });

  btnStyleBox.addEventListener("click", () => {
    state.highlightStyle = "box";
    btnStyleBox.classList.add("active");
    btnStyleColor.classList.remove("active");
    paneHighlightBox.classList.remove("hidden");
    paneHighlightBox.style.display = "";
    paneHighlightColor.classList.add("hidden");
    paneHighlightColor.style.display = "";
    state.stylingModified = true;
    renderSubtitlePreview();
  });

  colorHighlightText.addEventListener("input", (e) => {
    state.highlightColor = e.target.value.toUpperCase();
    codeHighlightText.textContent = state.highlightColor;
    if (state.isMultiSpeaker && state.speakerChannels && state.speakerChannels[state.activeSpeakerId]) {
      state.speakerChannels[state.activeSpeakerId].highlight_color = state.highlightColor;
      if (currentEditingSpeakerDot) {
        currentEditingSpeakerDot.style.background = state.highlightColor;
        currentEditingSpeakerDot.style.color = state.highlightColor;
      }
      const activeDot = speakerTabsBar ? speakerTabsBar.querySelector('.speaker-tab-btn.active .speaker-tab-dot') : null;
      if (activeDot) {
        activeDot.style.background = state.highlightColor;
        activeDot.style.color = state.highlightColor;
      }
    }
    state.stylingModified = true;
    renderSubtitlePreview();
  });

  swatchBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const c = btn.dataset.color;
      state.highlightColor = c;
      colorHighlightText.value = c;
      codeHighlightText.textContent = c;
      if (state.isMultiSpeaker && state.speakerChannels && state.speakerChannels[state.activeSpeakerId]) {
        state.speakerChannels[state.activeSpeakerId].highlight_color = c;
        if (currentEditingSpeakerDot) {
          currentEditingSpeakerDot.style.background = c;
          currentEditingSpeakerDot.style.color = c;
        }
        const activeDot = speakerTabsBar ? speakerTabsBar.querySelector('.speaker-tab-btn.active .speaker-tab-dot') : null;
        if (activeDot) {
          activeDot.style.background = c;
          activeDot.style.color = c;
        }
      }
      state.stylingModified = true;
      renderSubtitlePreview();
    });
  });

  const boxSwatchBtns = document.querySelectorAll(".swatch-box-bg");
  boxSwatchBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const c = btn.dataset.color;
      if (c) {
        state.boxBgColor = c.toUpperCase();
        if (colorBoxBg) colorBoxBg.value = c;
        if (codeBoxBg) codeBoxBg.textContent = c.toUpperCase();
        if (state.isMultiSpeaker && state.speakerChannels && state.speakerChannels[state.activeSpeakerId]) {
          state.speakerChannels[state.activeSpeakerId].box_bg_color = c.toUpperCase();
        }
        state.stylingModified = true;
        renderSubtitlePreview();
      }
    });
  });

  selectBoxType.addEventListener("change", (e) => {
    state.boxType = e.target.value;
    state.stylingModified = true;
    renderSubtitlePreview();
  });

  sliderBoxOpacity.addEventListener("input", (e) => {
    state.boxOpacity = parseInt(e.target.value) / 100;
    labelBoxOpacity.textContent = `${e.target.value}%`;
    state.stylingModified = true;
    renderSubtitlePreview();
  });

  colorBoxBg.addEventListener("input", (e) => {
    state.boxBgColor = e.target.value.toUpperCase();
    codeBoxBg.textContent = state.boxBgColor;
    if (state.isMultiSpeaker && state.speakerChannels && state.speakerChannels[state.activeSpeakerId]) {
      state.speakerChannels[state.activeSpeakerId].box_bg_color = state.boxBgColor;
    }
    state.stylingModified = true;
    renderSubtitlePreview();
  });

  colorBoxFont.addEventListener("input", (e) => {
    state.boxFontColor = e.target.value.toUpperCase();
    codeBoxFont.textContent = state.boxFontColor;
    if (state.isMultiSpeaker && state.speakerChannels && state.speakerChannels[state.activeSpeakerId]) {
      state.speakerChannels[state.activeSpeakerId].box_font_color = state.boxFontColor;
    }
    state.stylingModified = true;
    renderSubtitlePreview();
  });

  // Highlight Font Size Boost Slider
  if (sliderHighlightScale) {
    sliderHighlightScale.addEventListener("input", (e) => {
      state.highlightScalePct = parseInt(e.target.value);
      if (labelHighlightScale) labelHighlightScale.textContent = `${state.highlightScalePct}%`;
      state.stylingModified = true;
      renderSubtitlePreview();
    });
  }

  // Highlight Animation & Transition Effect
  if (selectHighlightAnimation) {
    selectHighlightAnimation.addEventListener("change", (e) => {
      state.highlightAnimation = e.target.value;
      state.stylingModified = true;
      renderSubtitlePreview();
    });
  }

  // Line Limits
  linePillBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      linePillBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.maxLines = parseInt(btn.dataset.lines);
      state.stylingModified = true;
      renderSubtitlePreview();
    });
  });

  sliderMaxChars.addEventListener("input", (e) => {
    state.maxChars = parseInt(e.target.value);
    labelMaxChars.textContent = `${state.maxChars} chars`;
    state.stylingModified = true;
    renderSubtitlePreview();
  });

  // Line Width Slider Listener
  sliderLineWidth.addEventListener("input", (e) => {
    state.lineWidthPct = parseInt(e.target.value);
    labelLineWidth.textContent = `${state.lineWidthPct}%`;
    state.stylingModified = true;
    renderSubtitlePreview();
  });

  // ----------------------------------------------------
  // 4a. Word Spelling List Controller (Pre-Transcription Biasing)
  // ----------------------------------------------------
  function sanitizeVocabTerm(term) {
    if (!term || typeof term !== "string") return "";
    return term.replace(/[<>"'`;\\{}[\]^~#$@!%*+=?|]/g, "").replace(/\s+/g, " ").trim();
  }

  function renderVocabChips() {
    if (!vocabChipsList) return;
    vocabChipsList.innerHTML = "";

    const terms = Array.isArray(state.customVocabulary) ? state.customVocabulary : [];
    const count = terms.length;

    if (vocabCountBadge) {
      vocabCountBadge.textContent = `${count} ${count === 1 ? "word" : "words"}`;
    }

    if (vocabEmptyHint) {
      vocabEmptyHint.style.display = count === 0 ? "" : "none";
    }

    terms.forEach((term, idx) => {
      const chip = document.createElement("span");
      chip.className = "vocab-chip";
      chip.dataset.index = String(idx);
      chip.title = "Click pencil or double-click to edit spelling";

      const textSpan = document.createElement("span");
      textSpan.className = "vocab-chip-text";
      textSpan.textContent = term;

      const editIcon = document.createElement("span");
      editIcon.className = "vocab-chip-edit-icon";
      editIcon.title = "Edit spelling";
      editIcon.textContent = "✏️";

      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "vocab-chip-remove";
      removeBtn.title = `Remove "${term}"`;
      removeBtn.innerHTML = "&times;";

      chip.appendChild(textSpan);
      chip.appendChild(editIcon);
      chip.appendChild(removeBtn);

      function startInlineEdit() {
        const input = document.createElement("input");
        input.type = "text";
        input.className = "vocab-chip-inline-input";
        input.value = term;

        chip.innerHTML = "";
        chip.appendChild(input);
        input.focus();
        input.select();

        let finished = false;
        function commitEdit(newVal) {
          if (finished) return;
          finished = true;
          const cleaned = sanitizeVocabTerm(newVal);
          if (!cleaned) {
            state.customVocabulary.splice(idx, 1);
          } else {
            const existingIdx = state.customVocabulary.findIndex((w, i) => i !== idx && w.toLowerCase() === cleaned.toLowerCase());
            if (existingIdx !== -1) {
              state.customVocabulary.splice(idx, 1);
            } else {
              state.customVocabulary[idx] = cleaned;
            }
          }
          state.stylingModified = true;
          renderVocabChips();
        }

        input.addEventListener("keydown", (e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commitEdit(input.value);
          } else if (e.key === "Escape") {
            e.preventDefault();
            finished = true;
            renderVocabChips();
          }
        });

        input.addEventListener("blur", () => {
          commitEdit(input.value);
        });
      }

      editIcon.addEventListener("click", (e) => {
        e.stopPropagation();
        startInlineEdit();
      });

      chip.addEventListener("dblclick", (e) => {
        e.stopPropagation();
        startInlineEdit();
      });

      removeBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        state.customVocabulary.splice(idx, 1);
        state.stylingModified = true;
        renderVocabChips();
      });

      vocabChipsList.appendChild(chip);
    });
  }

  function addVocabWords(rawInput) {
    if (!rawInput || typeof rawInput !== "string") return 0;
    const tokens = rawInput.split(/[\r\n,]+/).map(t => sanitizeVocabTerm(t)).filter(Boolean);
    if (!tokens.length) return 0;

    let addedCount = 0;
    if (!Array.isArray(state.customVocabulary)) {
      state.customVocabulary = [];
    }

    tokens.forEach(tok => {
      const exists = state.customVocabulary.some(w => w.toLowerCase() === tok.toLowerCase());
      if (!exists) {
        state.customVocabulary.push(tok);
        addedCount++;
      }
    });

    if (addedCount > 0) {
      state.stylingModified = true;
      renderVocabChips();
    }
    return addedCount;
  }

  // Wire Word Spelling List Controls
  if (btnAddVocab && inputCustomVocab) {
    btnAddVocab.addEventListener("click", () => {
      const val = inputCustomVocab.value;
      if (val && val.trim()) {
        addVocabWords(val);
        inputCustomVocab.value = "";
        inputCustomVocab.focus();
      }
    });

    inputCustomVocab.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        const val = inputCustomVocab.value;
        if (val && val.trim()) {
          addVocabWords(val);
          inputCustomVocab.value = "";
        }
      }
    });
  }

  // 📁 From File Import
  if (btnHarvestFile && inputVocabFile) {
    btnHarvestFile.addEventListener("click", () => {
      inputVocabFile.click();
    });

    inputVocabFile.addEventListener("change", (e) => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;

      const reader = new FileReader();
      reader.onload = (event) => {
        try {
          const content = event.target.result;
          let terms = [];

          if (file.name.toLowerCase().endsWith(".json")) {
            const parsed = JSON.parse(content);
            if (Array.isArray(parsed)) {
              terms = parsed.map(String);
            } else if (parsed && typeof parsed === "object") {
              const list = parsed.vocabulary || parsed.words || parsed.terms || parsed.custom_vocabulary || [];
              if (Array.isArray(list)) terms = list.map(String);
            }
          } else {
            // .txt or .csv
            terms = content.split(/[\r\n,]+/).map(s => s.trim()).filter(Boolean);
          }

          let added = 0;
          if (!Array.isArray(state.customVocabulary)) {
            state.customVocabulary = [];
          }

          terms.forEach(t => {
            const sanitized = sanitizeVocabTerm(t);
            if (sanitized) {
              const exists = state.customVocabulary.some(w => w.toLowerCase() === sanitized.toLowerCase());
              if (!exists) {
                state.customVocabulary.push(sanitized);
                added++;
              }
            }
          });

          if (added > 0) {
            state.stylingModified = true;
            renderVocabChips();
            showPresetStatus(`Imported ${added} new word(s) from "${file.name}"`);
          } else {
            showPresetStatus(`No new words added from "${file.name}" (already in list or empty)`);
          }
        } catch (err) {
          alert(`Could not parse file "${file.name}": ${err.message}`);
        } finally {
          inputVocabFile.value = "";
        }
      };

      reader.onerror = () => {
        alert(`Failed to read file "${file.name}".`);
        inputVocabFile.value = "";
      };

      reader.readAsText(file, "UTF-8");
    });
  }

  // 💾 Save Word Spelling List to File
  if (btnSaveVocabFile) {
    btnSaveVocabFile.addEventListener("click", async () => {
      const words = Array.isArray(state.customVocabulary) ? state.customVocabulary : [];
      if (!words.length) {
        showPresetStatus("No words in the spelling list to save. Add words first.");
        return;
      }

      // Generate clean default filename derived from current video or fallback
      let baseName = "word_spelling_list";
      if (state.videoPath) {
        const rawFilename = state.videoPath.split(/[/\\]/).pop() || "";
        const cleanBase = rawFilename.replace(/\.[^/.]+$/, "").replace(/[^a-zA-Z0-9_-]/g, "_").replace(/_+/g, "_").replace(/^_+|_+$/g, "");
        if (cleanBase) {
          baseName = `${cleanBase}_vocabulary`;
        }
      }
      const defaultFilename = `${baseName}.txt`;
      const fileText = words.join("\n") + "\n";

      // File System Access API with native 'Save As' dialog when supported
      if (window.showSaveFilePicker) {
        try {
          const handle = await window.showSaveFilePicker({
            suggestedName: defaultFilename,
            types: [{
              description: "Plain Text Vocabulary List (*.txt)",
              accept: { "text/plain": [".txt"] }
            }]
          });
          const writable = await handle.createWritable();
          await writable.write(fileText);
          await writable.close();
          showPresetStatus(`Saved ${words.length} word(s) to "${handle.name || defaultFilename}"!`);
          return;
        } catch (err) {
          if (err && err.name === "AbortError") {
            return;
          }
        }
      }

      // Universal cross-browser Blob download fallback
      try {
        const blob = new Blob([fileText], { type: "text/plain;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = defaultFilename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showPresetStatus(`Saved ${words.length} word(s) to "${defaultFilename}"!`);
      } catch (err) {
        alert(`Could not save file: ${err.message}`);
      }
    });
  }

  // 👥 From Speakers Import
  if (btnHarvestSpeakers) {
    btnHarvestSpeakers.addEventListener("click", () => {
      const channels = state.speakerChannels || {};
      const activeKeys = Object.keys(channels).slice(0, Math.max(1, state.speakerCount || 1));
      const genericRegex = /^speaker[\s_]*([0-9]+)?$/i;
      const candidates = [];

      activeKeys.forEach(k => {
        const spk = channels[k];
        if (spk && spk.name) {
          const trimmed = spk.name.trim();
          if (trimmed && !genericRegex.test(trimmed)) {
            candidates.push(trimmed);
          }
        }
      });

      if (!candidates.length) {
        showPresetStatus("No custom speaker names found. Enter names under 'Highlight Style > Multi-Speaker' first.");
        return;
      }

      let added = 0;
      if (!Array.isArray(state.customVocabulary)) {
        state.customVocabulary = [];
      }

      candidates.forEach(name => {
        const sanitized = sanitizeVocabTerm(name);
        if (sanitized) {
          const exists = state.customVocabulary.some(w => w.toLowerCase() === sanitized.toLowerCase());
          if (!exists) {
            state.customVocabulary.push(sanitized);
            added++;
          }
        }
      });

      if (added > 0) {
        state.stylingModified = true;
        renderVocabChips();
        showPresetStatus(`Added ${added} speaker name(s) to spelling list`);
      } else {
        showPresetStatus("Speaker names are already in the spelling list");
      }
    });
  }

  // 🗑️ Clear All
  if (btnClearVocab) {
    btnClearVocab.addEventListener("click", () => {
      if (state.customVocabulary && state.customVocabulary.length > 0) {
        state.customVocabulary = [];
        state.stylingModified = true;
        renderVocabChips();
        showPresetStatus("Word spelling list cleared");
      }
    });
  }

  // ----------------------------------------------------
  // 4b. Multi-Speaker Color Channels System (Up to 5 Voices)
  // ----------------------------------------------------
  const DEFAULT_SPEAKER_PALETTE = ["#FFDF00", "#00E5FF", "#FF007F", "#00FF66", "#B026FF", "#FF9900", "#D8B4FE", "#F43F5E"];

  function ensureSpeakerChannels(count) {
    const targetCount = Math.max(2, Math.min(count || 5, 5));
    for (let i = 0; i < targetCount; i++) {
      const spkId = `SPEAKER_0${i}`;
      if (!state.speakerChannels[spkId]) {
        state.speakerChannels[spkId] = {
          id: spkId,
          name: `Speaker ${i + 1}`,
          primary_color: "#FFFFFF",
          highlight_color: DEFAULT_SPEAKER_PALETTE[i % DEFAULT_SPEAKER_PALETTE.length],
          outline_color: "#000000",
          box_bg_color: "#000000",
          box_font_color: "#FFFFFF",
          show_speaker_name: false
        };
      }
    }
  }

  function setMultiSpeakerMode(enabled, count = null) {
    state.isMultiSpeaker = !!enabled;
    if (enabled) {
      const voiceCount = count || (state.speakerCount >= 2 ? state.speakerCount : 5);
      state.speakerCount = voiceCount;
      ensureSpeakerChannels(voiceCount);

      if (speakerChannelsSection) speakerChannelsSection.classList.remove("hidden");
      if (btnModeMultiSpeaker) {
        btnModeMultiSpeaker.classList.add("active");
        btnModeMultiSpeaker.setAttribute("aria-selected", "true");
      }
      if (btnModeSingleSpeaker) {
        btnModeSingleSpeaker.classList.remove("active");
        btnModeSingleSpeaker.setAttribute("aria-selected", "false");
      }
      if (speakerCountBadge) speakerCountBadge.textContent = `${voiceCount} Voices`;

      // Highlight active count selector pill
      if (countPillBtns && countPillBtns.length > 0) {
        countPillBtns.forEach(btn => {
          const btnCount = parseInt(btn.dataset.count, 10);
          btn.classList.toggle("active", btnCount === voiceCount);
        });
      }

      const activeKeys = Object.keys(state.speakerChannels).slice(0, voiceCount);
      if (!activeKeys.includes(state.activeSpeakerId)) {
        state.activeSpeakerId = activeKeys[0] || "SPEAKER_00";
      }

      renderSpeakerTabs();
      syncActiveSpeakerUI();
    } else {
      if (speakerChannelsSection) speakerChannelsSection.classList.add("hidden");
      if (btnModeSingleSpeaker) {
        btnModeSingleSpeaker.classList.add("active");
        btnModeSingleSpeaker.setAttribute("aria-selected", "true");
      }
      if (btnModeMultiSpeaker) {
        btnModeMultiSpeaker.classList.remove("active");
        btnModeMultiSpeaker.setAttribute("aria-selected", "false");
      }
      if (speakerCountBadge) speakerCountBadge.textContent = "1 Voice";
    }

    renderSubtitlePreview();
    if (editorState.dialogues && editorState.dialogues.length > 0) {
      renderDrawerDialogueItems(editorState.dialogues);
    }
  }

  function updateSpeakerControlsVisibility(speakerCount, detectedSpeakers) {
    const count = Math.max(1, speakerCount || 1);
    state.speakerCount = count;

    if (count <= 1 && !state.isMultiSpeaker) {
      setMultiSpeakerMode(false);
    } else {
      if (detectedSpeakers && detectedSpeakers.length > 0) {
        detectedSpeakers.forEach((spkId, idx) => {
          if (!state.speakerChannels[spkId]) {
            state.speakerChannels[spkId] = {
              id: spkId,
              name: spkId.startsWith("SPEAKER_") ? `Speaker ${idx + 1}` : spkId,
              primary_color: "#FFFFFF",
              highlight_color: DEFAULT_SPEAKER_PALETTE[idx % DEFAULT_SPEAKER_PALETTE.length],
              outline_color: "#000000",
              box_bg_color: "#000000",
              box_font_color: "#FFFFFF",
              show_speaker_name: false
            };
          }
        });
      }
      setMultiSpeakerMode(true, Math.max(count, (detectedSpeakers ? detectedSpeakers.length : 2)));
    }
  }

  function renderSpeakerTabs() {
    if (!speakerTabsBar) return;
    speakerTabsBar.innerHTML = "";
    const limit = state.isMultiSpeaker ? state.speakerCount : 2;
    const keys = Object.keys(state.speakerChannels).slice(0, limit);

    keys.forEach(key => {
      const ch = state.speakerChannels[key];
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `speaker-tab-btn ${key === state.activeSpeakerId ? "active" : ""}`;
      btn.dataset.speakerId = key;
      btn.setAttribute("role", "tab");
      btn.setAttribute("aria-selected", key === state.activeSpeakerId ? "true" : "false");
      btn.innerHTML = `
        <span class="speaker-tab-dot" style="background:${ch.highlight_color || '#FFDF00'}; color:${ch.highlight_color || '#FFDF00'};"></span>
        <span class="speaker-tab-name">${ch.name || key}</span>
      `;

      btn.addEventListener("click", () => {
        state.activeSpeakerId = key;
        speakerTabsBar.querySelectorAll(".speaker-tab-btn").forEach(b => {
          const isActive = (b.dataset.speakerId === key);
          b.classList.toggle("active", isActive);
          b.setAttribute("aria-selected", isActive ? "true" : "false");
        });
        syncActiveSpeakerUI();
        renderSubtitlePreview();
      });

      speakerTabsBar.appendChild(btn);
    });
  }

  function syncActiveSpeakerUI() {
    if (!state.isMultiSpeaker || !state.speakerChannels) return;
    const ch = state.speakerChannels[state.activeSpeakerId] || Object.values(state.speakerChannels)[0];
    if (!ch) return;

    if (currentEditingSpeakerName) currentEditingSpeakerName.textContent = ch.name || ch.id;
    if (currentEditingSpeakerDot) {
      currentEditingSpeakerDot.style.background = ch.highlight_color || "#FFDF00";
      currentEditingSpeakerDot.style.color = ch.highlight_color || "#FFDF00";
    }
    if (inputSpeakerDisplayName) inputSpeakerDisplayName.value = ch.name || ch.id;

    if (colorSpeakerHighlight) {
      colorSpeakerHighlight.value = ch.highlight_color || "#FFDF00";
    }
    if (codeSpeakerHighlight) {
      codeSpeakerHighlight.textContent = (ch.highlight_color || "#FFDF00").toUpperCase();
    }

    if (ch.highlight_color && colorHighlightText) {
      colorHighlightText.value = ch.highlight_color;
      if (codeHighlightText) codeHighlightText.textContent = ch.highlight_color;
      state.highlightColor = ch.highlight_color;
    }
    if (ch.primary_color && colorTextBase) {
      colorTextBase.value = ch.primary_color;
      if (codeTextBase) codeTextBase.textContent = ch.primary_color;
      state.textBaseColor = ch.primary_color;
    }
    if (ch.outline_color && colorOutline) {
      colorOutline.value = ch.outline_color;
      if (codeOutline) codeOutline.textContent = ch.outline_color;
      state.outlineColor = ch.outline_color;
    }
    if (ch.box_bg_color && colorBoxBg) {
      colorBoxBg.value = ch.box_bg_color;
      if (codeBoxBg) codeBoxBg.textContent = ch.box_bg_color;
      state.boxBgColor = ch.box_bg_color;
    }

    updateSpeakerSampleUI();
  }

  function updateSpeakerSampleUI() {
    if (!speakerSamplePlayerRow || !btnPlaySpeakerSample) return;
    const currentSpk = state.activeSpeakerId || "SPEAKER_00";
    const sample = state.speakerSamples ? state.speakerSamples[currentSpk] : null;

    if (sample && sample.sample_url) {
      btnPlaySpeakerSample.disabled = false;
      btnPlaySpeakerSample.classList.remove("disabled");
      if (speakerSampleQuote) {
        const quoteText = sample.quote ? `"${sample.quote}"` : `Sample for ${sample.speaker_name || currentSpk}`;
        speakerSampleQuote.textContent = `${quoteText} (${sample.duration || 2.5}s)`;
        speakerSampleQuote.style.color = "var(--text-main, #f8fafc)";
      }
    } else {
      btnPlaySpeakerSample.disabled = true;
      btnPlaySpeakerSample.classList.add("disabled");
      if (speakerSampleQuote) {
        speakerSampleQuote.textContent = state.isMultiSpeaker
          ? "Voice sample ready after transcription"
          : "Enable Multi-Speaker Diarization to hear voice samples";
        speakerSampleQuote.style.color = "var(--text-muted, #94a3b8)";
      }
      if (speakerSampleAudio && !speakerSampleAudio.paused) {
        speakerSampleAudio.pause();
      }
      if (speakerSamplePlayIcon) speakerSamplePlayIcon.textContent = "▶";
      if (speakerSamplePlayText) speakerSamplePlayText.textContent = "Listen";
    }
  }

  if (btnPlaySpeakerSample && speakerSampleAudio) {
    btnPlaySpeakerSample.addEventListener("click", () => {
      const currentSpk = state.activeSpeakerId || "SPEAKER_00";
      const sample = state.speakerSamples ? state.speakerSamples[currentSpk] : null;
      if (!sample || !sample.sample_url) return;

      if (!speakerSampleAudio.paused) {
        speakerSampleAudio.pause();
        speakerSampleAudio.currentTime = 0;
        if (speakerSamplePlayIcon) speakerSamplePlayIcon.textContent = "▶";
        if (speakerSamplePlayText) speakerSamplePlayText.textContent = "Listen";
        return;
      }

      const token = state.authToken || (new URLSearchParams(window.location.search)).get("token") || "";
      let playUrl = sample.sample_url;
      if (token) {
        playUrl += (playUrl.includes("?") ? "&" : "?") + `token=${encodeURIComponent(token)}`;
      }

      speakerSampleAudio.src = playUrl;
      speakerSampleAudio.play().then(() => {
        if (speakerSamplePlayIcon) speakerSamplePlayIcon.textContent = "⏹";
        if (speakerSamplePlayText) speakerSamplePlayText.textContent = "Stop";
      }).catch(err => {
        console.warn("Could not play speaker sample audio:", err);
      });
    });

    speakerSampleAudio.addEventListener("ended", () => {
      if (speakerSamplePlayIcon) speakerSamplePlayIcon.textContent = "▶";
      if (speakerSamplePlayText) speakerSamplePlayText.textContent = "Listen";
    });

    speakerSampleAudio.addEventListener("error", () => {
      if (speakerSamplePlayIcon) speakerSamplePlayIcon.textContent = "▶";
      if (speakerSamplePlayText) speakerSamplePlayText.textContent = "Listen";
    });
  }

  if (checkEnableDiarization) {
    checkEnableDiarization.addEventListener("change", () => {
      state.enableDiarization = checkEnableDiarization.checked;
      if (checkEnableDiarization.checked && !state.isMultiSpeaker) {
        setMultiSpeakerMode(true, Math.max(2, state.speakerCount || 2));
      }
    });
  }

  if (btnModeSingleSpeaker) {
    btnModeSingleSpeaker.addEventListener("click", () => {
      setMultiSpeakerMode(false);
      if (checkEnableDiarization) {
        checkEnableDiarization.checked = false;
        state.enableDiarization = false;
      }
    });
  }

  if (btnModeMultiSpeaker) {
    btnModeMultiSpeaker.addEventListener("click", () => {
      setMultiSpeakerMode(true, state.speakerCount >= 2 ? state.speakerCount : 5);
      if (checkEnableDiarization) {
        checkEnableDiarization.checked = true;
        state.enableDiarization = true;
      }
    });
  }

  if (btnToggleSpeakerChannels) {
    btnToggleSpeakerChannels.addEventListener("click", () => {
      setMultiSpeakerMode(!state.isMultiSpeaker, state.speakerCount >= 2 ? state.speakerCount : 5);
    });
  }

  if (countPillBtns && countPillBtns.length > 0) {
    countPillBtns.forEach(btn => {
      btn.addEventListener("click", () => {
        const count = parseInt(btn.dataset.count, 10);
        if (count >= 2 && count <= 5) {
          setMultiSpeakerMode(true, count);
        }
      });
    });
  }

  if (colorSpeakerHighlight) {
    colorSpeakerHighlight.addEventListener("input", (e) => {
      const val = e.target.value.toUpperCase();
      if (codeSpeakerHighlight) codeSpeakerHighlight.textContent = val;
      if (state.isMultiSpeaker && state.speakerChannels && state.speakerChannels[state.activeSpeakerId]) {
        state.speakerChannels[state.activeSpeakerId].highlight_color = val;
        if (colorHighlightText) colorHighlightText.value = val;
        if (codeHighlightText) codeHighlightText.textContent = val;
        state.highlightColor = val;
        if (currentEditingSpeakerDot) currentEditingSpeakerDot.style.background = val;
        renderSpeakerTabs();
        renderSubtitlePreview();
        if (editorState.dialogues && editorState.dialogues.length > 0) {
          renderDrawerDialogueItems(editorState.dialogues);
        }
      }
    });
  }

  if (speakerSwatchChips && speakerSwatchChips.length > 0) {
    speakerSwatchChips.forEach(chip => {
      chip.addEventListener("click", () => {
        const c = chip.dataset.color.toUpperCase();
        if (colorSpeakerHighlight) colorSpeakerHighlight.value = c;
        if (codeSpeakerHighlight) codeSpeakerHighlight.textContent = c;
        if (state.isMultiSpeaker && state.speakerChannels && state.speakerChannels[state.activeSpeakerId]) {
          state.speakerChannels[state.activeSpeakerId].highlight_color = c;
          if (colorHighlightText) colorHighlightText.value = c;
          if (codeHighlightText) codeHighlightText.textContent = c;
          state.highlightColor = c;
          if (currentEditingSpeakerDot) currentEditingSpeakerDot.style.background = c;
          renderSpeakerTabs();
          renderSubtitlePreview();
          if (editorState.dialogues && editorState.dialogues.length > 0) {
            renderDrawerDialogueItems(editorState.dialogues);
          }
        }
      });
    });
  }

  if (inputSpeakerDisplayName) {
    inputSpeakerDisplayName.addEventListener("input", (e) => {
      if (state.isMultiSpeaker && state.speakerChannels && state.speakerChannels[state.activeSpeakerId]) {
        const val = e.target.value.trim() || state.activeSpeakerId;
        state.speakerChannels[state.activeSpeakerId].name = val;
        if (currentEditingSpeakerName) currentEditingSpeakerName.textContent = val;
        renderSpeakerTabs();
        if (editorState.dialogues && editorState.dialogues.length > 0) {
          renderDrawerDialogueItems(editorState.dialogues);
        }
      }
    });
  }

  const themeChips = document.querySelectorAll(".theme-chip");
  themeChips.forEach(chip => {
    chip.addEventListener("click", () => {
      const theme = chip.dataset.theme;
      ensureSpeakerChannels(5);

      if (theme === "yellow-cyan") {
        state.speakerCount = 2;
        state.speakerChannels["SPEAKER_00"].highlight_color = "#FFDF00";
        state.speakerChannels["SPEAKER_00"].name = "Speaker 1";
        state.speakerChannels["SPEAKER_01"].highlight_color = "#00E5FF";
        state.speakerChannels["SPEAKER_01"].name = "Speaker 2";
      } else if (theme === "lime-pink") {
        state.speakerCount = 2;
        state.speakerChannels["SPEAKER_00"].highlight_color = "#00FF66";
        state.speakerChannels["SPEAKER_00"].name = "Speaker 1";
        state.speakerChannels["SPEAKER_01"].highlight_color = "#FF007F";
        state.speakerChannels["SPEAKER_01"].name = "Speaker 2";
      } else if (theme === "trio") {
        state.speakerCount = 3;
        state.speakerChannels["SPEAKER_00"].highlight_color = "#FFDF00";
        state.speakerChannels["SPEAKER_00"].name = "Speaker 1";
        state.speakerChannels["SPEAKER_01"].highlight_color = "#00E5FF";
        state.speakerChannels["SPEAKER_01"].name = "Speaker 2";
        state.speakerChannels["SPEAKER_02"].highlight_color = "#FF007F";
        state.speakerChannels["SPEAKER_02"].name = "Speaker 3";
      } else if (theme === "quintet") {
        state.speakerCount = 5;
        state.speakerChannels["SPEAKER_00"].highlight_color = "#FFDF00";
        state.speakerChannels["SPEAKER_00"].name = "Speaker 1";
        state.speakerChannels["SPEAKER_01"].highlight_color = "#00E5FF";
        state.speakerChannels["SPEAKER_01"].name = "Speaker 2";
        state.speakerChannels["SPEAKER_02"].highlight_color = "#FF007F";
        state.speakerChannels["SPEAKER_02"].name = "Speaker 3";
        state.speakerChannels["SPEAKER_03"].highlight_color = "#00FF66";
        state.speakerChannels["SPEAKER_03"].name = "Speaker 4";
        state.speakerChannels["SPEAKER_04"].highlight_color = "#B026FF";
        state.speakerChannels["SPEAKER_04"].name = "Speaker 5";
      }

      setMultiSpeakerMode(true, state.speakerCount);
    });
  });

  // Output Mode Selector (if present)
  if (outputModeBtns && outputModeBtns.length > 0) {
    outputModeBtns.forEach(btn => {
      btn.addEventListener("click", () => {
        outputModeBtns.forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        state.outputMode = btn.dataset.mode;
      });
    });
  }

  // Custom Output Filename Input
  if (outputFilenameInput) {
    outputFilenameInput.addEventListener("input", (e) => {
      state.outputFilename = e.target.value.trim();
      syncDeliverableFilenames();
    });
  }

  // Social Media Platform & Device Selectors
  socialPlatformBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      socialPlatformBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.socialPlatform = btn.dataset.platform;
      renderSocialOverlay();
    });
  });

  socialDeviceBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      socialDeviceBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.socialDevice = btn.dataset.device;
      renderSocialOverlay();
    });
  });

  // ----------------------------------------------------
  // Social Media UI Overlay Generator
  // ----------------------------------------------------
  function renderSocialOverlay() {
    if (state.socialPlatform === "none") {
      socialUiLayer.classList.add("hidden");
      socialUiLayer.innerHTML = "";
      return;
    }

    socialUiLayer.classList.remove("hidden");
    const isMobile = state.socialDevice === "mobile";

    if (state.socialPlatform === "youtube") {
      if (isMobile) {
        // YouTube Shorts Mobile App UI
        socialUiLayer.innerHTML = `
          <div class="social-top-bar">
            <span>Shorts</span>
            <div class="social-top-icons">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 7l-7 5 7 5V7z"></path><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="2"></circle><circle cx="12" cy="12" r="2"></circle><circle cx="12" cy="19" r="2"></circle></svg>
            </div>
          </div>

          <div class="social-right-bar">
            <div class="social-action-btn">
              <div class="social-action-icon"><svg viewBox="0 0 24 24"><path d="M1 21h4V9H1v12zm22-11c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-2z"/></svg></div>
              <span class="social-action-count">184K</span>
            </div>
            <div class="social-action-btn">
              <div class="social-action-icon"><svg viewBox="0 0 24 24"><path d="M15 3H6c-.83 0-1.54.5-1.84 1.22l-3.02 7.05c-.09.23-.14.47-.14.73v2c0 1.1.9 2 2 2h6.31l-.95 4.57-.03.32c0 .41.17.79.44 1.06L9.83 23l6.59-6.59c.36-.36.58-.86.58-1.41V5c0-1.1-.9-2-2-2zm4 0v12h4V3h-4z"/></svg></div>
              <span class="social-action-count">Dislike</span>
            </div>
            <div class="social-action-btn">
              <div class="social-action-icon"><svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-1.99.9-1.99 2L2 22l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zM6 9h12v2H6V9zm8 5H6v-2h8v2zm4-6H6V6h12v2z"/></svg></div>
              <span class="social-action-count">1.4K</span>
            </div>
            <div class="social-action-btn">
              <div class="social-action-icon"><svg viewBox="0 0 24 24"><path d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92s2.92-1.31 2.92-2.92-1.31-2.92-2.92-2.92z"/></svg></div>
              <span class="social-action-count">Share</span>
            </div>
            <div class="yt-sound-disc"></div>
          </div>

          <div class="social-bottom-bar">
            <div class="social-user-row">
              <div class="social-avatar yt-avatar">CS</div>
              <span class="social-username">@creator_studio</span>
              <span class="social-follow-pill yt-pill">Subscribe</span>
            </div>
            <div class="social-caption">Captivating vertical content with AI animated word highlights.</div>
            <div class="social-audio-tag">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/></svg>
              <span>Original audio — Creator Studio</span>
            </div>
          </div>
        `;
      } else {
        // YouTube Shorts Web Desktop UI
        socialUiLayer.innerHTML = `
          <div class="web-player-chrome">
            <div class="web-top-bar">
              <span>▶ YouTube Shorts (Web Browser)</span>
              <span>1080p • 60fps</span>
            </div>
            <div class="social-right-bar" style="bottom: 75px;">
              <div class="social-action-btn"><div class="social-action-icon"><svg viewBox="0 0 24 24"><path d="M1 21h4V9H1v12zm22-11c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-2z"/></svg></div><span class="social-action-count">184K</span></div>
              <div class="social-action-btn"><div class="social-action-icon"><svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-1.99.9-1.99 2L2 22l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg></div><span class="social-action-count">1.4K</span></div>
              <div class="social-action-btn"><div class="social-action-icon"><svg viewBox="0 0 24 24"><path d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92s2.92-1.31 2.92-2.92-1.31-2.92-2.92-2.92z"/></svg></div><span class="social-action-count">Share</span></div>
            </div>
            <div class="web-bottom-bar">
              <div class="web-progress-track"><div class="web-progress-fill"></div></div>
              <div class="web-controls-row">
                <span>0:14 / 0:45</span>
                <span class="social-username">@creator_studio • Subscribe</span>
              </div>
            </div>
          </div>
        `;
      }
    } else if (state.socialPlatform === "instagram") {
      if (isMobile) {
        // Instagram Reels Mobile App UI
        socialUiLayer.innerHTML = `
          <div class="social-top-bar">
            <span class="ig-reels-title">Reels ▾</span>
            <div class="social-top-icons">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="4"></circle></svg>
            </div>
          </div>

          <div class="social-right-bar">
            <div class="social-action-btn">
              <div class="social-action-icon"><svg viewBox="0 0 24 24"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg></div>
              <span class="social-action-count">94.2K</span>
            </div>
            <div class="social-action-btn">
              <div class="social-action-icon"><svg viewBox="0 0 24 24"><path d="M21.99 4c0-1.1-.89-2-1.99-2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h14l4 4-.01-18zM18 14H6v-2h12v2zm0-3H6V9h12v2zm0-3H6V6h12v2z"/></svg></div>
              <span class="social-action-count">830</span>
            </div>
            <div class="social-action-btn">
              <div class="social-action-icon"><svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg></div>
              <span class="social-action-count">Share</span>
            </div>
            <div class="social-action-btn">
              <div class="social-action-icon"><svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="2"></circle><circle cx="12" cy="12" r="2"></circle><circle cx="19" cy="12" r="2"></circle></svg></div>
            </div>
            <div class="social-avatar" style="border-radius: 4px; width: 26px; height: 26px;">♫</div>
          </div>

          <div class="social-bottom-bar">
            <div class="social-user-row">
              <div class="social-avatar">CS</div>
              <span class="social-username">creator_studio</span>
              <span class="social-follow-pill ig-pill">Follow</span>
            </div>
            <div class="social-caption">Captivating vertical reels with AI animated word highlights... <strong>more</strong></div>
            <div class="social-audio-tag">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/></svg>
              <span>creator_studio • Original Audio</span>
            </div>
          </div>
        `;
      } else {
        // Instagram Reels Web Desktop UI
        socialUiLayer.innerHTML = `
          <div class="web-player-chrome">
            <div class="web-top-bar">
              <span>📷 Instagram Reels (Web Browser)</span>
              <span>🔊 Audio On</span>
            </div>
            <div class="social-right-bar" style="bottom: 60px;">
              <div class="social-action-btn"><div class="social-action-icon"><svg viewBox="0 0 24 24"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg></div><span class="social-action-count">94.2K</span></div>
              <div class="social-action-btn"><div class="social-action-icon"><svg viewBox="0 0 24 24"><path d="M21.99 4c0-1.1-.89-2-1.99-2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h14l4 4-.01-18z"/></svg></div><span class="social-action-count">830</span></div>
            </div>
            <div class="social-bottom-bar" style="bottom: 12px;">
              <div class="social-user-row">
                <div class="social-avatar">CS</div>
                <span class="social-username">creator_studio • Follow</span>
              </div>
              <div class="social-caption">High-impact vertical video styling and word highlighting</div>
            </div>
          </div>
        `;
      }
    } else if (state.socialPlatform === "facebook") {
      if (isMobile) {
        // Facebook Reels Mobile UI
        socialUiLayer.innerHTML = `
          <div class="social-top-bar">
            <span>Reels</span>
            <div class="social-top-icons">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="2"></circle><circle cx="12" cy="12" r="2"></circle><circle cx="12" cy="19" r="2"></circle></svg>
            </div>
          </div>

          <div class="social-right-bar">
            <div class="social-action-btn">
              <div class="social-action-icon"><svg viewBox="0 0 24 24"><path d="M1 21h4V9H1v12zm22-11c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-2z"/></svg></div>
              <span class="social-action-count">45K</span>
            </div>
            <div class="social-action-btn">
              <div class="social-action-icon"><svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-1.99.9-1.99 2L2 22l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg></div>
              <span class="social-action-count">612</span>
            </div>
            <div class="social-action-btn">
              <div class="social-action-icon"><svg viewBox="0 0 24 24"><path d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92s2.92-1.31 2.92-2.92-1.31-2.92-2.92-2.92z"/></svg></div>
              <span class="social-action-count">Share</span>
            </div>
          </div>

          <div class="social-bottom-bar">
            <div class="social-user-row">
              <div class="social-avatar fb-avatar">CS</div>
              <span class="social-username">Creator Studio</span>
              <span class="social-follow-pill fb-pill">Follow</span>
            </div>
            <div class="social-caption">Captivating video content with AI animated word highlights.</div>
          </div>
        `;
      } else {
        // Facebook Video Web Desktop UI
        socialUiLayer.innerHTML = `
          <div class="web-player-chrome">
            <div class="web-top-bar">
              <span>Facebook Video Player (Web Browser)</span>
              <span>HD 1080p</span>
            </div>
            <div class="web-bottom-bar">
              <div class="web-progress-track"><div class="web-progress-fill" style="background:#1877f2;"></div></div>
              <div class="web-controls-row">
                <span>▶ 0:18 / 0:45 • 🔊</span>
                <span>Creator Studio</span>
              </div>
            </div>
          </div>
        `;
      }
    }
  }

  // Preview Text Switcher
  if (btnTextDefault) {
    if (!state.hasExistingAss) {
      btnTextDefault.disabled = true;
      btnTextDefault.classList.add("disabled");
      btnTextDefault.title = "Transcript unavailable. Generate subtitles (.ass) first in Step 1.";
    }

    btnTextDefault.addEventListener("click", () => {
      if (btnTextDefault.disabled) return;
      btnTextDefault.classList.add("active");
      if (btnTextLorem) btnTextLorem.classList.remove("active");
      if (editorState.dialogues && editorState.dialogues.length > 0 && editorState.dialogues[0].clean_text) {
        previewTextInput.value = editorState.dialogues[0].clean_text.replace(/\\N/gi, " ").replace(/\\h/gi, " ").replace(/\s+/g, " ").trim();
      } else {
        previewTextInput.value = "Voice Highlighter Subtitles Preview";
      }
      state.previewText = previewTextInput.value;
      state.activeWordIndex = 0;
      renderSubtitlePreview();
    });
  }

  if (btnTextLorem) {
    btnTextLorem.addEventListener("click", () => {
      btnTextLorem.classList.add("active");
      if (btnTextDefault) btnTextDefault.classList.remove("active");
      previewTextInput.value = "Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt.";
      state.previewText = previewTextInput.value;
      state.activeWordIndex = 0;
      renderSubtitlePreview();
    });
  }

  if (previewTextInput) {
    previewTextInput.addEventListener("input", (e) => {
      state.previewText = e.target.value || "Lorem ipsum dolor sit amet";
      state.activeWordIndex = 0;
      renderSubtitlePreview();
    });
  }

  // Toggle Subtitle Bounds Envelope
  if (btnToggleBounds) {
    btnToggleBounds.addEventListener("click", () => {
      state.showBounds = !state.showBounds;
      updateBoundsEnvelope();
    });
  }

  if (videoPathInput) {
    videoPathInput.addEventListener("input", (e) => {
      state.videoPath = e.target.value.trim();
    });
  }



  // ----------------------------------------------------
  // 5. Submit Job & Progress Polling
  // ----------------------------------------------------
  function updateStepper(step) {
    stepNodeExtract.classList.remove("active", "completed");
    stepNodeWhisper.classList.remove("active", "completed");
    stepNodeAlign.classList.remove("active", "completed");
    stepNodeAss.classList.remove("active", "completed");
    if (stepNodeBurn) stepNodeBurn.classList.remove("active", "completed");

    if (step === 1) {
      stepNodeExtract.classList.add("active");
    } else if (step === 2) {
      stepNodeExtract.classList.add("completed");
      stepNodeWhisper.classList.add("active");
    } else if (step === 3) {
      stepNodeExtract.classList.add("completed");
      stepNodeWhisper.classList.add("completed");
      stepNodeAlign.classList.add("active");
    } else if (step === 4) {
      stepNodeExtract.classList.add("completed");
      stepNodeWhisper.classList.add("completed");
      stepNodeAlign.classList.add("completed");
      stepNodeAss.classList.add("active");
    } else if (step === 5) {
      stepNodeExtract.classList.add("completed");
      stepNodeWhisper.classList.add("completed");
      stepNodeAlign.classList.add("completed");
      stepNodeAss.classList.add("completed");
      if (stepNodeBurn) stepNodeBurn.classList.add("active");
    } else if (step >= 6) {
      stepNodeExtract.classList.add("completed");
      stepNodeWhisper.classList.add("completed");
      stepNodeAlign.classList.add("completed");
      stepNodeAss.classList.add("completed");
      if (stepNodeBurn) stepNodeBurn.classList.add("completed");
    }
  }

  // ----------------------------------------------------
  // In-Place Studio Progress Thermometer & Delivery Controls
  // ----------------------------------------------------
  const studioProgressThermometer = document.getElementById("studioProgressThermometer");
  const thermometerTitle = document.getElementById("thermometerTitle");
  const thermometerPercentBadge = document.getElementById("thermometerPercentBadge");
  const thermometerVitalsBadge = document.getElementById("thermometerVitalsBadge");
  const thermometerEtaMessage = document.getElementById("thermometerEtaMessage");
  const thermometerFill = document.getElementById("thermometerFill");
  const thermometerStageMessage = document.getElementById("thermometerStageMessage");
  const msAudio = document.getElementById("msAudio");
  const msWhisper = document.getElementById("msWhisper");
  const msAlign = document.getElementById("msAlign");
  const msAss = document.getElementById("msAss");
  const msBurn = document.getElementById("msBurn");
  const btnInspectAssStudio = document.getElementById("btnInspectAssStudio");

  function showThermometer(title, initialPercent = 0, initialMsg = "Initializing...") {
    if (burnedDeliveryBanner) burnedDeliveryBanner.classList.add("hidden");
    if (studioProgressThermometer) {
      studioProgressThermometer.classList.remove("hidden");
      if (thermometerTitle) thermometerTitle.textContent = title;
      if (thermometerPercentBadge) thermometerPercentBadge.textContent = `${initialPercent}%`;
      if (thermometerFill) thermometerFill.style.width = `${initialPercent}%`;
      if (thermometerStageMessage) {
        thermometerStageMessage.textContent = initialMsg;
        thermometerStageMessage.style.color = "#93c5fd";
      }
      if (thermometerVitalsBadge) thermometerVitalsBadge.classList.add("hidden");
      if (thermometerEtaMessage) thermometerEtaMessage.classList.add("hidden");
    }
  }

  function updateThermometer(percent, stageMsg, milestoneIndex = 1, customTitle = null, telemetry = null) {
    if (!studioProgressThermometer) return;
    studioProgressThermometer.classList.remove("hidden");
    const pct = Math.max(0, Math.min(100, Math.round(percent)));
    if (thermometerPercentBadge) thermometerPercentBadge.textContent = `${pct}%`;
    if (thermometerFill) thermometerFill.style.width = `${pct}%`;
    if (stageMsg && thermometerStageMessage) thermometerStageMessage.textContent = stageMsg;
    if (customTitle && thermometerTitle) thermometerTitle.textContent = customTitle;

    if (telemetry && (telemetry.speed || telemetry.fps || telemetry.frame)) {
      if (thermometerVitalsBadge) {
        const speedVal = (telemetry.speed || 1.0).toFixed(1);
        const fpsVal = Math.round(telemetry.fps || 0);
        const frameVal = (telemetry.frame || 0).toLocaleString();
        thermometerVitalsBadge.textContent = `⚡ ${speedVal}x • ${fpsVal} fps • Frame ${frameVal}`;
        thermometerVitalsBadge.classList.remove("hidden");
      }
      if (thermometerEtaMessage && (telemetry.eta_seconds > 0 || telemetry.duration > 0)) {
        const etaSec = Math.round(telemetry.eta_seconds || 0);
        const etaText = etaSec > 0 ? `~${etaSec}s remaining` : "finishing...";
        const curSec = Math.round(telemetry.current_seconds || 0);
        const durSec = Math.round(telemetry.duration || 0);
        const curMin = Math.floor(curSec / 60);
        const curS = String(curSec % 60).padStart(2, "0");
        const durMin = Math.floor(durSec / 60);
        const durS = String(durSec % 60).padStart(2, "0");
        thermometerEtaMessage.textContent = `⏱️ ${etaText} (${curMin}:${curS} / ${durMin}:${durS})`;
        thermometerEtaMessage.classList.remove("hidden");
      }
    } else {
      if (thermometerVitalsBadge) thermometerVitalsBadge.classList.add("hidden");
      if (thermometerEtaMessage) thermometerEtaMessage.classList.add("hidden");
    }

    const milestones = [msAudio, msWhisper, msAlign, msAss, msBurn];
    milestones.forEach((el, idx) => {
      if (!el) return;
      const num = idx + 1;
      if (num < milestoneIndex) {
        el.className = "milestone-pill completed";
      } else if (num === milestoneIndex) {
        el.className = "milestone-pill active";
      } else {
        el.className = "milestone-pill";
      }
    });
  }

  function hideThermometer() {
    if (studioProgressThermometer) {
      studioProgressThermometer.classList.add("hidden");
      if (thermometerVitalsBadge) thermometerVitalsBadge.classList.add("hidden");
      if (thermometerEtaMessage) thermometerEtaMessage.classList.add("hidden");
    }
  }

  function showDeliveryBanner(videoPath, filename = null) {
    hideThermometer();
    if (burnedDeliveryBanner) {
      burnedDeliveryBanner.classList.remove("hidden");
      if (burnedVideoPathText) burnedVideoPathText.textContent = videoPath;
      state.lastBurnedVideoPath = videoPath;
      state.lastBurnedVideoFilename = filename || (videoPath ? videoPath.split("/").pop() : null);
      syncDeliverableFilenames();
      burnedDeliveryBanner.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  if (btnInspectAssStudio) {
    btnInspectAssStudio.addEventListener("click", () => {
      if (cardSubtitleDrawer) {
        cardSubtitleDrawer.classList.remove("collapsed");
        cardSubtitleDrawer.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  }

  async function pollStatus(taskId) {
    try {
      const res = await fetch(`/api/status/${taskId}`);
      if (!res.ok) return;
      const data = await res.json();

      const milestone = data.progress < 25 ? 1 : data.progress < 60 ? 2 : data.progress < 85 ? 3 : data.progress < 94 ? 4 : 5;
      updateThermometer(
        data.progress,
        data.stage_message,
        milestone,
        data.burn_video ? "Transcribing & Burning Video (RTX A5000 NVENC)..." : "Generating Subtitles (.ass) with WhisperX...",
        data.burn_telemetry
      );

      // Keep legacy anchors updated for backwards compatibility
      if (progressBarFill) progressBarFill.style.width = `${data.progress}%`;
      if (statusPercent) statusPercent.textContent = `${data.progress}%`;
      if (statusStageMessage) statusStageMessage.textContent = data.stage_message;

      // Progressive disclosure: Activate Step 2 & Dialog Transcript as soon as .ass is ready
      if (data.ass_ready) {
        state.hasExistingAss = true;
        state.existingAssPath = data.download_url;
        state.existingAssName = `${data.custom_filename || 'subtitles'}.ass`;

        if (btnTextDefault) {
          btnTextDefault.disabled = false;
          btnTextDefault.classList.remove("disabled");
          btnTextDefault.title = "Preview subtitle text from dialogue";
        }
        if (btnFocusStep2) {
          btnFocusStep2.classList.remove("disabled");
        }
        if (btnBurnOnly) {
          btnBurnOnly.classList.remove("disabled");
        }
        if (btnDownloadAss && data.download_url) {
          btnDownloadAss.href = data.download_url;
          if (data.custom_filename) btnDownloadAss.download = `${data.custom_filename}.ass`;
        }

        // Refresh Subtitle File Hub details from disk
        if (!state.hubLoadedForTask || state.hubLoadedForTask !== taskId) {
          state.hubLoadedForTask = taskId;
          refreshAssFileInfo({ taskId, mediaPath: state.videoPath });
        }
      }

      if (data.speaker_samples) {
        state.speakerSamples = data.speaker_samples;
        updateSpeakerSampleUI();
      }
      if (data.speakers_found && data.speakers_found.length > 1) {
        state.isMultiSpeaker = true;
        updateSpeakerControlsVisibility(data.speakers_found.length, data.speakers_found);
      }

      if (data.status === "completed") {
        clearInterval(state.pollInterval);
        state.pollInterval = null;
        updateThermometer(100, "Done! Process completed successfully.", 5);
        setTimeout(() => hideThermometer(), 1000);

        state.currentTaskId = data.task_id;
        state.hasExistingAss = true;
        state.existingAssPath = data.download_url;
        state.existingAssName = `${data.custom_filename || 'subtitles'}.ass`;

        if (btnDownloadAss) {
          btnDownloadAss.href = data.download_url;
          if (data.custom_filename) btnDownloadAss.download = `${data.custom_filename}.ass`;
        }

        // Refresh disk info for the newly created .ass file
        refreshAssFileInfo({ taskId: data.task_id, mediaPath: state.videoPath });

        if (data.video_download_url || data.video_file) {
          const finalVideoPath = data.video_file || `${state.videoPath || ''}`;
          state.lastBurnedVideoPath = finalVideoPath;
          state.lastBurnedVideoFilename = data.video_filename || `${data.custom_filename || 'video'}.mp4`;
          showDeliveryBanner(finalVideoPath, state.lastBurnedVideoFilename);
          updateWorkflowStepper('burned');
        } else {
          if (burnedDeliveryBanner) burnedDeliveryBanner.classList.add("hidden");
          updateWorkflowStepper('subtitles_ready');
          // Automatically bring Subtitle File & External Editor Hub into view
          if (cardAssFileHub) {
            cardAssFileHub.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          }
        }
        syncDeliverableFilenames();

        if (codeBodyPreview) codeBodyPreview.textContent = data.ass_preview || "; Generated Subtitles Ready";
        if (btnGenerateAssOnly) btnGenerateAssOnly.classList.remove('disabled');
        if (btnTranscribeAndBurn) btnTranscribeAndBurn.classList.remove('disabled');
        if (btnBurnOnly) btnBurnOnly.classList.remove('disabled');
      } else if (data.status === "error") {
        clearInterval(state.pollInterval);
        state.pollInterval = null;
        updateThermometer(100, `Error: ${data.error}`, 1, "Failed");
        if (thermometerStageMessage) thermometerStageMessage.style.color = "#f87171";
        if (btnGenerateAssOnly) btnGenerateAssOnly.classList.remove('disabled');
        if (btnTranscribeAndBurn) btnTranscribeAndBurn.classList.remove('disabled');
        updateWorkflowStepper('idle');
      }
    } catch (e) {
      console.error("Polling error:", e);
    }
  }

  // ----------------------------------------------------
  // Primary Workflow Execution Functions (Tasks 1, 2, 4)
  // ----------------------------------------------------
  async function executeTranscription(burnVideo = false) {
    const videoPath = (videoPathInput ? videoPathInput.value.trim() : "") || state.videoPath;
    if (!videoPath) {
      alert("Please provide or browse to a valid video file.");
      openNativeFileDialog();
      return;
    }
    state.videoPath = videoPath;

    const selectModelName = document.getElementById("selectModelName");
    const chosenModel = selectModelName ? selectModelName.value : "large-v3";
    const customFilename = outputFilenameInput ? outputFilenameInput.value.trim() : state.outputFilename;

    const payload = {
      video_path: videoPath,
      model_name: chosenModel,
      burn_video: burnVideo,
      output_filename: customFilename || null,
      reuse_existing_ass: false,
      reuse_existing_wav: false,
      enable_diarization: Boolean((checkEnableDiarization && checkEnableDiarization.checked) || state.enableDiarization || state.isMultiSpeaker),
      custom_vocabulary: Array.isArray(state.customVocabulary) ? [...state.customVocabulary] : [],
      styling: getCurrentStylingPayload()
    };

    updateWorkflowStepper(burnVideo ? 'burning' : 'transcribing');
    if (btnGenerateAssOnly) btnGenerateAssOnly.classList.add('disabled');
    if (btnTranscribeAndBurn) btnTranscribeAndBurn.classList.add('disabled');

    // Show horizontal thermometer directly below action buttons
    showThermometer(
      burnVideo ? "Transcribing & Burning Video (WhisperX + NVENC)..." : "Generating Subtitles (.ass) with WhisperX...",
      5,
      "Initializing WhisperX speech recognition pipeline..."
    );

    try {
      const res = await fetch("/api/transcribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Submission failed");
      }
      const data = await res.json();
      state.currentTaskId = data.task_id;

      if (state.pollInterval) clearInterval(state.pollInterval);
      state.pollInterval = setInterval(() => pollStatus(state.currentTaskId), 850);
      pollStatus(state.currentTaskId);
    } catch (err) {
      alert(`Error starting transcription: ${err.message}`);
      if (btnGenerateAssOnly) btnGenerateAssOnly.classList.remove('disabled');
      if (btnTranscribeAndBurn) btnTranscribeAndBurn.classList.remove('disabled');
      hideThermometer();
      updateWorkflowStepper('idle');
    }
  }

  // Task 4: Fast NVENC Burn Video from Current / Edited ASS
  async function executeBurnVideo() {
    const videoPath = (videoPathInput ? videoPathInput.value.trim() : '') || state.videoPath;
    if (!videoPath) {
      alert("Please provide or load a video file first.");
      openNativeFileDialog();
      return;
    }
    state.videoPath = videoPath;

    const effectiveAss = editorState.assPath || state.existingAssPath;
    if (!effectiveAss && !editorState.currentContent) {
      alert("No subtitles (.ass) found to burn. Please generate subtitles first using Step 1.");
      return;
    }

    updateWorkflowStepper('burning');
    updateDrawerStatus('Burning subtitles with NVIDIA RTX A5000 NVENC...', 'normal');
    if (btnBurnOnly) btnBurnOnly.classList.add('disabled');
    if (btnDrawerBurn) {
      btnDrawerBurn.disabled = true;
      btnDrawerBurn.textContent = 'Burning...';
    }
    if (btnModalSaveAndBurn) {
      btnModalSaveAndBurn.disabled = true;
      btnModalSaveAndBurn.textContent = 'Burning...';
    }

    const burnTaskId = state.currentTaskId || editorState.taskId || (`burn_${Date.now()}`);

    // Show horizontal thermometer progress meter directly below buttons
    showThermometer("Burning Video with Hardware Acceleration...", 5, "Compiling ASS dialogue events and starting encoder...");
    if (state.pollInterval) clearInterval(state.pollInterval);
    state.pollInterval = setInterval(() => pollStatus(burnTaskId), 500);

    try {
      // Direct disk-first load: Never send in-memory buffer content.
      // FFmpeg burns directly from the .ass file saved on disk (including external editor edits).
      const payload = {
        video_path: videoPath,
        ass_path: effectiveAss,
        task_id: burnTaskId,
        output_filename: (outputFilenameInput ? outputFilenameInput.value.trim() : null) || state.outputFilename,
        content: null,
        styling: getCurrentStylingPayload(),
        styling_modified: !!state.stylingModified
      };

      const res = await fetch('/api/burn-video', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (state.pollInterval) {
        clearInterval(state.pollInterval);
        state.pollInterval = null;
      }

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Subtitle burning failed');
      }

      const data = await res.json();
      state.stylingModified = false;

      // Refresh .ass metadata & dialogue from disk
      if (data.task_id || data.ass_filename) {
        refreshAssFileInfo({ filePath: effectiveAss, taskId: data.task_id, mediaPath: videoPath });
      }

      updateWorkflowStepper('burned');

      state.lastBurnedVideoPath = data.video_path || data.video_file;
      state.lastBurnedVideoFilename = data.video_filename || (state.lastBurnedVideoPath ? state.lastBurnedVideoPath.split("/").pop() : null);
      if (data.ass_filename) {
        state.hasExistingAss = true;
        state.existingAssName = data.ass_filename;
      }
      syncDeliverableFilenames();

      updateThermometer(100, "✓ Hardware transcode complete! Deliverable ready.", 5);
      setTimeout(() => {
        showDeliveryBanner(state.lastBurnedVideoPath, data.video_filename);
      }, 700);

      if (btnDownloadAss && data.download_url) {
        btnDownloadAss.href = data.download_url;
        if (data.ass_filename) btnDownloadAss.download = data.ass_filename;
      }
    } catch (err) {
      if (state.pollInterval) {
        clearInterval(state.pollInterval);
        state.pollInterval = null;
      }
      console.error("Burn video error:", err);
      alert(`Error burning video: ${err.message}`);
      updateThermometer(100, `Error: ${err.message}`, 5, "Burn Failed");
      updateWorkflowStepper('subtitles_ready');
    } finally {
      if (btnBurnOnly) btnBurnOnly.classList.remove('disabled');
    }
  }

  // Wire primary action triggers
  if (btnGenerateAssOnly) {
    btnGenerateAssOnly.addEventListener("click", () => executeTranscription(false));
  }
  if (btnTranscribeAndBurn) {
    btnTranscribeAndBurn.addEventListener("click", () => executeTranscription(true));
  }
  if (btnBurnOnly) {
    btnBurnOnly.addEventListener("click", () => executeBurnVideo());
  }
  if (btnSubmit) {
    btnSubmit.addEventListener("click", () => executeTranscription(state.outputMode === "burn"));
  }

  // Copy ASS code
  btnCopyAss.addEventListener("click", () => {
    navigator.clipboard.writeText(codeBodyPreview.textContent).then(() => {
      copyBtnText.textContent = "Copied to Clipboard!";
      setTimeout(() => { copyBtnText.textContent = "Copy ASS Script"; }, 2000);
    });
  });

  // ----------------------------------------------------
  // Presets Management System (LocalStorage + JSON Export/Import)
  // ----------------------------------------------------
  const PRESET_STORAGE_KEY = "voice_highlighter_custom_presets";
  const PRESET_LAST_ACTIVE_KEY = "voice_highlighter_last_active_preset";

  const FACTORY_PRESETS = {
    "factory:tiktok_pop": {
      name: "🔥 Viral TikTok (Yellow Pop)",
      styling: {
        posX: 50,
        posY: 78,
        fontFamily: "Montserrat",
        fontSize: 22,
        primaryColor: "#ffffff",
        outlineColor: "#000000",
        outlineWidth: 4,
        bold: true,
        italic: false,
        highlightStyle: "color",
        highlightColor: "#ffd700",
        highlightScale: 125,
        maxLines: 1,
        lineWidthPct: 82,
        maxChars: 28
      }
    },
    "factory:hormozi_box": {
      name: "🏷️ Hormozi Pill Box",
      styling: {
        posX: 50,
        posY: 78,
        fontFamily: "Montserrat",
        fontSize: 22,
        primaryColor: "#ffffff",
        outlineColor: "#000000",
        outlineWidth: 0,
        bold: true,
        italic: false,
        highlightStyle: "box",
        boxType: "word",
        boxOpacity: 0.90,
        boxBgColor: "#ffd700",
        boxFontColor: "#000000",
        highlightScale: 115,
        maxLines: 1,
        lineWidthPct: 82,
        maxChars: 28
      }
    },
    "factory:classic_sub": {
      name: "🎬 Classic Subtitle (2 Lines)",
      styling: {
        posX: 50,
        posY: 82,
        fontFamily: "Inter",
        fontSize: 20,
        primaryColor: "#ffffff",
        outlineColor: "#000000",
        outlineWidth: 3,
        bold: false,
        italic: false,
        highlightStyle: "color",
        highlightColor: "#00e5ff",
        highlightScale: 100,
        maxLines: 2,
        lineWidthPct: 85,
        maxChars: 32
      }
    },
    "factory:clean_minimal": {
      name: "✨ Clean Minimalist",
      styling: {
        posX: 50,
        posY: 75,
        fontFamily: "Inter",
        fontSize: 18,
        primaryColor: "#ffffff",
        outlineColor: "#000000",
        outlineWidth: 2,
        bold: false,
        italic: false,
        highlightStyle: "color",
        highlightColor: "#10b981",
        highlightScale: 105,
        maxLines: 1,
        lineWidthPct: 80,
        maxChars: 26
      }
    },
    "factory:podcast_duo": {
      name: "🎙️ Podcast Duo (Multi-Speaker)",
      styling: {
        posX: 50,
        posY: 78,
        fontFamily: "Inter",
        fontSize: 22,
        primaryColor: "#ffffff",
        outlineColor: "#000000",
        outlineWidth: 3.5,
        bold: true,
        italic: false,
        highlightStyle: "color",
        highlightColor: "#ffd700",
        highlightScale: 115,
        maxLines: 1,
        lineWidthPct: 82,
        maxChars: 28,
        speaker_channels: {
          "SPEAKER_00": {
            id: "SPEAKER_00",
            name: "Host",
            primary_color: "#ffffff",
            highlight_color: "#ffd700",
            outline_color: "#000000",
            box_bg_color: "#000000",
            box_font_color: "#ffffff",
            show_speaker_name: false
          },
          "SPEAKER_01": {
            id: "SPEAKER_01",
            name: "Guest",
            primary_color: "#ffffff",
            highlight_color: "#00e5ff",
            outline_color: "#000000",
            box_bg_color: "#000000",
            box_font_color: "#ffffff",
            show_speaker_name: false
          }
        }
      }
    },
    "factory:ensemble_quintet": {
      name: "🎭 Ensemble Quintet (5 Voices)",
      styling: {
        posX: 50,
        posY: 78,
        fontFamily: "Montserrat",
        fontSize: 22,
        primaryColor: "#ffffff",
        outlineColor: "#000000",
        outlineWidth: 3.5,
        bold: true,
        italic: false,
        highlightStyle: "color",
        highlightColor: "#ffdf00",
        highlightScale: 115,
        maxLines: 1,
        lineWidthPct: 82,
        maxChars: 28,
        speaker_channels: {
          "SPEAKER_00": {
            id: "SPEAKER_00",
            name: "Speaker 1",
            primary_color: "#ffffff",
            highlight_color: "#ffdf00",
            outline_color: "#000000",
            box_bg_color: "#000000",
            box_font_color: "#ffffff",
            show_speaker_name: false
          },
          "SPEAKER_01": {
            id: "SPEAKER_01",
            name: "Speaker 2",
            primary_color: "#ffffff",
            highlight_color: "#00e5ff",
            outline_color: "#000000",
            box_bg_color: "#000000",
            box_font_color: "#ffffff",
            show_speaker_name: false
          },
          "SPEAKER_02": {
            id: "SPEAKER_02",
            name: "Speaker 3",
            primary_color: "#ffffff",
            highlight_color: "#ff007f",
            outline_color: "#000000",
            box_bg_color: "#000000",
            box_font_color: "#ffffff",
            show_speaker_name: false
          },
          "SPEAKER_03": {
            id: "SPEAKER_03",
            name: "Speaker 4",
            primary_color: "#ffffff",
            highlight_color: "#00ff66",
            outline_color: "#000000",
            box_bg_color: "#000000",
            box_font_color: "#ffffff",
            show_speaker_name: false
          },
          "SPEAKER_04": {
            id: "SPEAKER_04",
            name: "Speaker 5",
            primary_color: "#ffffff",
            highlight_color: "#b026ff",
            outline_color: "#000000",
            box_bg_color: "#000000",
            box_font_color: "#ffffff",
            show_speaker_name: false
          }
        }
      }
    },
    "factory:laser_karaoke": {
      name: "🎤 LaserKaraoke Wipe (Smooth Sweep)",
      styling: {
        posX: 50,
        posY: 80,
        fontFamily: "Montserrat",
        fontSize: 24,
        primaryColor: "#ffffff",
        outlineColor: "#000000",
        outlineWidth: 4,
        bold: true,
        italic: false,
        highlightStyle: "color",
        highlightColor: "#ffdf00",
        highlightScale: 110,
        highlightAnimation: "karaoke_wipe",
        maxLines: 1,
        lineWidthPct: 82,
        maxChars: 28
      }
    }
  };

  let presetDrawerMode = "save"; // 'save' or 'rename'

  function getCustomPresets() {
    try {
      const raw = localStorage.getItem(PRESET_STORAGE_KEY);
      const presets = raw ? JSON.parse(raw) : {};
      return presets;
    } catch (e) {
      console.warn("Failed to read presets from localStorage:", e);
      return {};
    }
  }

  function setCustomPresets(presets) {
    try {
      localStorage.setItem(PRESET_STORAGE_KEY, JSON.stringify(presets));
    } catch (e) {
      console.warn("Failed to write presets to localStorage:", e);
    }
  }

  async function persistPresetToBackend(slug, displayName, snapshot) {
    try {
      const payload = {
        name: slug,
        description: displayName,
        font_name: snapshot.fontFamily || "Montserrat",
        font_size: Number(snapshot.fontSize) || 68,
        bold: Boolean(snapshot.bold),
        italic: Boolean(snapshot.italic),
        primary_color: snapshot.primaryColor || "#FFFFFF",
        outline_color: snapshot.outlineColor || "#000000",
        outline_width: Number(snapshot.outlineWidth) !== undefined ? Number(snapshot.outlineWidth) : 3.0,
        highlight_style: snapshot.highlightStyle || "color",
        highlight_color: snapshot.highlightColor || "#FFDF00",
        box_bg_color: snapshot.boxBgColor || "#000000",
        box_opacity: snapshot.boxOpacity !== undefined ? Number(snapshot.boxOpacity) : 0.85,
        box_font_color: snapshot.boxFontColor || "#FFFFFF",
        box_type: snapshot.boxType || "word",
        highlight_scale_pct: Number(snapshot.highlightScale) || 100,
        pos_x_pct: snapshot.posX !== undefined ? Number(snapshot.posX) : 50,
        pos_y_pct: snapshot.posY !== undefined ? Number(snapshot.posY) : 78,
        line_width_pct: snapshot.lineWidthPct !== undefined ? Number(snapshot.lineWidthPct) : 82,
        max_lines: Number(snapshot.maxLines) || 1,
        max_chars_per_line: Number(snapshot.maxChars) || 28,
        highlight_animation: snapshot.highlightAnimation || "discrete",
        speaker_channels: snapshot.speaker_channels || {},
        custom_vocabulary: snapshot.custom_vocabulary || [],
        keyframes: Array.isArray(snapshot.keyframes) ? snapshot.keyframes : []
      };

      const res = await fetch("/api/presets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        console.warn("Could not save preset to disk:", res.status);
      }
    } catch (e) {
      console.warn("Failed to persist preset to backend disk:", e);
    }
  }

  async function deletePresetFromBackend(slug) {
    try {
      await fetch(`/api/presets/${encodeURIComponent(slug)}`, {
        method: "DELETE"
      });
    } catch (e) {
      console.warn("Failed to delete preset from backend disk:", e);
    }
  }

  async function syncPresetsFromBackend() {
    try {
      const res = await fetch("/api/presets");
      if (!res.ok) return;
      const data = await res.json();
      if (!data || !Array.isArray(data.presets)) return;

      const custom = getCustomPresets();
      let updated = false;

      for (const presetName of data.presets) {
        if (presetName === "default") continue;
        const id = "custom_" + presetName;
        try {
          const pRes = await fetch(`/api/presets/${encodeURIComponent(presetName)}`);
          if (pRes.ok) {
            const pData = await pRes.json();
            custom[id] = {
              id: id,
              name: pData.description || presetName,
              slug: presetName,
              updated_at: new Date().toISOString(),
              styling: {
                posX: pData.pos_x_pct !== undefined ? pData.pos_x_pct : 50,
                posY: pData.pos_y_pct !== undefined ? pData.pos_y_pct : 78,
                fontFamily: pData.font_name || "Montserrat",
                fontSize: pData.font_size || 68,
                primaryColor: pData.primary_color || "#FFFFFF",
                outlineColor: pData.outline_color || "#000000",
                outlineWidth: pData.outline_width !== undefined ? pData.outline_width : 3.0,
                bold: pData.bold !== undefined ? pData.bold : true,
                italic: pData.italic !== undefined ? pData.italic : false,
                highlightStyle: pData.highlight_style || "color",
                highlightColor: pData.highlight_color || "#FFDF00",
                highlightScale: pData.highlight_scale_pct || 100,
                highlightAnimation: pData.highlight_animation || "discrete",
                boxType: pData.box_type || "word",
                boxOpacity: pData.box_opacity !== undefined ? pData.box_opacity : 0.85,
                boxBgColor: pData.box_bg_color || "#000000",
                boxFontColor: pData.box_font_color || "#FFFFFF",
                maxLines: pData.max_lines || 1,
                lineWidthPct: pData.line_width_pct !== undefined ? pData.line_width_pct : 82,
                maxChars: pData.max_chars_per_line || 28,
                speaker_channels: pData.speaker_channels || {},
                custom_vocabulary: pData.custom_vocabulary || [],
                keyframes: Array.isArray(pData.keyframes) ? pData.keyframes : []
              }
            };
            updated = true;
          }
        } catch (err) {
          console.warn(`Failed to fetch preset ${presetName} from backend:`, err);
        }
      }

      if (updated) {
        setCustomPresets(custom);
        const lastActive = localStorage.getItem(PRESET_LAST_ACTIVE_KEY);
        populatePresetDropdown(lastActive || (selectPreset ? selectPreset.value : ""));
      }
    } catch (e) {
      console.warn("Failed to sync presets from backend:", e);
    }
  }

  function showPresetStatus(msg) {
    if (!presetStatusMsg) return;
    presetStatusMsg.textContent = msg;
    presetStatusMsg.style.display = "block";
    setTimeout(() => {
      if (presetStatusMsg) presetStatusMsg.style.display = "none";
    }, 3200);
  }

  function populatePresetDropdown(selectedId) {
    if (!optgroupCustom || !selectPreset) return;
    optgroupCustom.innerHTML = "";
    const custom = getCustomPresets();
    const ids = Object.keys(custom);

    ids.forEach(id => {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = `★ ${custom[id].name}`;
      optgroupCustom.appendChild(opt);
    });

    if (selectedId) {
      selectPreset.value = selectedId;
    }
    updatePresetToolbarState();
  }

  function updatePresetToolbarState() {
    const val = selectPreset.value;
    const isCustom = val && val.startsWith("custom_");
    if (btnUpdatePreset) {
      btnUpdatePreset.disabled = !isCustom;
      if (isCustom) {
        const custom = getCustomPresets();
        const p = custom[val];
        btnUpdatePreset.title = p ? `Update "${p.name}" with current styling` : "Update active custom preset";
      } else {
        btnUpdatePreset.title = "Default presets cannot be modified. Click 'Save New...' to save as a custom preset.";
      }
    }
    if (btnRenamePreset) btnRenamePreset.disabled = !isCustom;
    if (btnDeletePreset) btnDeletePreset.disabled = !isCustom;
  }

  function getCurrentStylingSnapshot(includeKeyframes = true) {
    const snapshot = {
      posX: state.posX,
      posY: state.posY,
      fontFamily: state.fontFamily,
      fontSize: state.fontSize,
      primaryColor: state.textBaseColor || state.primaryColor || "#FFFFFF",
      outlineColor: state.outlineColor,
      outlineWidth: state.outlineWidth,
      bold: state.bold,
      italic: state.italic,
      highlightStyle: state.highlightStyle,
      highlightColor: state.highlightColor,
      highlightScale: state.highlightScale || state.highlightScalePct,
      highlightAnimation: state.highlightAnimation || "discrete",
      boxType: state.boxType,
      boxOpacity: state.boxOpacity,
      boxBgColor: state.boxBgColor,
      boxFontColor: state.boxFontColor,
      maxLines: state.maxLines,
      lineWidthPct: state.lineWidthPct,
      maxChars: state.maxChars
    };
    if (includeKeyframes && state.keyframes && state.keyframes.length > 0) {
      snapshot.keyframes = JSON.parse(JSON.stringify(state.keyframes));
    }
    if (state.isMultiSpeaker && state.speakerCount >= 2 && state.speakerChannels) {
      snapshot.speaker_channels = JSON.parse(JSON.stringify(state.speakerChannels));
    }
    if (state.customVocabulary && state.customVocabulary.length > 0) {
      snapshot.custom_vocabulary = [...state.customVocabulary];
    }
    return snapshot;
  }

  function applyPresetStyling(styling, suppressDirty = false) {
    if (!styling) return;

    if (!suppressDirty) {
      if (Array.isArray(styling.keyframes)) {
        state.keyframes = JSON.parse(JSON.stringify(styling.keyframes));
      } else {
        state.keyframes = [];
      }
      state.activeKeyframeId = null;
      state.selectedKeyframeId = null;
      renderTimelineKeyframeMarkers();
      updateKeyframeToolbarAndBanner(state.currentSeekTime || 0);
    }

    // Position
    if (styling.posX !== undefined && styling.posY !== undefined) {
      updatePosition(styling.posX, styling.posY, true);
    }

    // Font Family
    if (styling.fontFamily && selectFontFamily) {
      selectFontFamily.value = styling.fontFamily;
      state.fontFamily = styling.fontFamily;
    }

    // Font Size
    if (styling.fontSize !== undefined && sliderFontSize) {
      sliderFontSize.value = styling.fontSize;
      if (labelFontSize) labelFontSize.textContent = `${styling.fontSize}px`;
      state.fontSize = Number(styling.fontSize);
    }

    // Colors
    if (styling.primaryColor && colorTextBase) {
      colorTextBase.value = styling.primaryColor;
      if (codeTextBase) codeTextBase.value = styling.primaryColor;
      state.primaryColor = styling.primaryColor;
    }

    if (styling.outlineColor && colorOutline) {
      colorOutline.value = styling.outlineColor;
      if (codeOutline) codeOutline.value = styling.outlineColor;
      state.outlineColor = styling.outlineColor;
    }

    if (styling.outlineWidth !== undefined && sliderOutlineWidth) {
      sliderOutlineWidth.value = styling.outlineWidth;
      if (labelOutlineWidth) labelOutlineWidth.textContent = `${styling.outlineWidth}px`;
      state.outlineWidth = Number(styling.outlineWidth);
    }

    // Bold / Italic
    if (styling.bold !== undefined && checkBold) {
      checkBold.checked = Boolean(styling.bold);
      state.bold = Boolean(styling.bold);
    }
    if (styling.italic !== undefined && checkItalic) {
      checkItalic.checked = Boolean(styling.italic);
      state.italic = Boolean(styling.italic);
    }

    // Highlight Style
    if (styling.highlightStyle || styling.highlight_style) {
      const hStyle = styling.highlightStyle || styling.highlight_style;
      state.highlightStyle = hStyle;
      if (hStyle === "box") {
        if (btnStyleBox) btnStyleBox.classList.add("active");
        if (btnStyleColor) btnStyleColor.classList.remove("active");
        if (paneHighlightBox) {
          paneHighlightBox.classList.remove("hidden");
          paneHighlightBox.style.display = "";
        }
        if (paneHighlightColor) {
          paneHighlightColor.classList.add("hidden");
          paneHighlightColor.style.display = "";
        }
      } else {
        if (btnStyleColor) btnStyleColor.classList.add("active");
        if (btnStyleBox) btnStyleBox.classList.remove("active");
        if (paneHighlightColor) {
          paneHighlightColor.classList.remove("hidden");
          paneHighlightColor.style.display = "";
        }
        if (paneHighlightBox) {
          paneHighlightBox.classList.add("hidden");
          paneHighlightBox.style.display = "";
        }
      }
    }

    if (styling.highlightColor && colorHighlightText) {
      colorHighlightText.value = styling.highlightColor;
      if (codeHighlightText) codeHighlightText.value = styling.highlightColor;
      state.highlightColor = styling.highlightColor;
    }

    // Highlight Font Size Boost
    if (styling.highlightScale !== undefined && sliderHighlightScale) {
      sliderHighlightScale.value = styling.highlightScale;
      if (labelHighlightScale) labelHighlightScale.textContent = `${styling.highlightScale}%`;
      state.highlightScale = Number(styling.highlightScale);
    }

    // Highlight Animation Mode (Pioneer/Sony expired prior art)
    if (styling.highlightAnimation || styling.highlight_animation) {
      const anim = styling.highlightAnimation || styling.highlight_animation;
      state.highlightAnimation = anim;
      if (selectHighlightAnimation) selectHighlightAnimation.value = anim;
    } else {
      state.highlightAnimation = "discrete";
      if (selectHighlightAnimation) selectHighlightAnimation.value = "discrete";
    }

    // Box settings
    if (styling.boxType && selectBoxType) {
      selectBoxType.value = styling.boxType;
      state.boxType = styling.boxType;
    }

    if (styling.boxOpacity !== undefined && sliderBoxOpacity) {
      sliderBoxOpacity.value = styling.boxOpacity;
      if (labelBoxOpacity) labelBoxOpacity.textContent = `${Math.round(styling.boxOpacity * 100)}%`;
      state.boxOpacity = Number(styling.boxOpacity);
    }

    if (styling.boxBgColor && colorBoxBg) {
      colorBoxBg.value = styling.boxBgColor;
      if (codeBoxBg) codeBoxBg.value = styling.boxBgColor;
      state.boxBgColor = styling.boxBgColor;
    }

    if (styling.boxFontColor && colorBoxFont) {
      colorBoxFont.value = styling.boxFontColor;
      if (codeBoxFont) codeBoxFont.value = styling.boxFontColor;
      state.boxFontColor = styling.boxFontColor;
    }

    // Lines & layout
    if (styling.maxLines !== undefined) {
      state.maxLines = Number(styling.maxLines);
      linePillBtns.forEach(btn => {
        btn.classList.toggle("active", Number(btn.dataset.lines) === state.maxLines);
      });
    }

    if (styling.lineWidthPct !== undefined && sliderLineWidth) {
      sliderLineWidth.value = styling.lineWidthPct;
      if (labelLineWidth) labelLineWidth.textContent = `${styling.lineWidthPct}%`;
      state.lineWidthPct = Number(styling.lineWidthPct);
    }

    const chars = styling.maxChars || styling.maxCharsPerLine;
    if (chars !== undefined && sliderMaxChars) {
      sliderMaxChars.value = chars;
      if (labelMaxChars) labelMaxChars.textContent = chars;
      state.maxChars = Number(chars);
    }

    // Multi-Speaker Color Channels
    if (styling.speaker_channels && Object.keys(styling.speaker_channels).length >= 2) {
      state.speakerChannels = JSON.parse(JSON.stringify(styling.speaker_channels));
      state.detectedSpeakers = Object.keys(styling.speaker_channels);
      state.speakerCount = Object.keys(styling.speaker_channels).length;
      state.isMultiSpeaker = true;
      if (!state.speakerChannels[state.activeSpeakerId]) {
        state.activeSpeakerId = state.detectedSpeakers[0];
      }
      updateSpeakerControlsVisibility(state.speakerCount, state.detectedSpeakers);
    } else if (styling.speaker_channels === undefined && !state.hasExistingAss) {
      // Single speaker preset: hide multi-speaker controls
      state.isMultiSpeaker = false;
      state.speakerCount = 1;
      updateSpeakerControlsVisibility(1);
    }

    // Word Spelling List Restoration
    if (styling.custom_vocabulary || styling.customVocabulary) {
      const vocab = styling.custom_vocabulary || styling.customVocabulary;
      state.customVocabulary = Array.isArray(vocab) ? [...vocab] : [];
      renderVocabChips();
    }

    // Refresh live preview canvas
    renderSubtitlePreview();
  }

  function loadAndApplyPreset(presetId) {
    if (!presetId) return;

    if (presetId.startsWith("factory:")) {
      const template = FACTORY_PRESETS[presetId];
      if (template) {
        state.basePresetStyling = JSON.parse(JSON.stringify(template.styling));
        applyPresetStyling(template.styling);
        showPresetStatus(`Applied template: ${template.name}`);
        localStorage.setItem(PRESET_LAST_ACTIVE_KEY, presetId);
      }
    } else {
      const custom = getCustomPresets();
      const p = custom[presetId];
      if (p) {
        state.basePresetStyling = JSON.parse(JSON.stringify(p.styling));
        applyPresetStyling(p.styling);
        showPresetStatus(`Applied preset: ${p.name}`);
        localStorage.setItem(PRESET_LAST_ACTIVE_KEY, presetId);
      }
    }
    updatePresetToolbarState();
  }

  // Preset Selection Listener
  if (selectPreset) {
    selectPreset.addEventListener("change", (e) => {
      loadAndApplyPreset(e.target.value);
    });
  }

  if (btnApplyPreset) {
    btnApplyPreset.addEventListener("click", () => {
      loadAndApplyPreset(selectPreset.value);
    });
  }

  // Update Custom Preset Trigger
  if (btnUpdatePreset) {
    btnUpdatePreset.addEventListener("click", () => {
      const val = selectPreset.value;
      if (!val || !val.startsWith("custom_")) {
        showPresetStatus("Default presets cannot be modified. Click 'Save New...' to save a custom preset.");
        return;
      }
      const custom = getCustomPresets();
      const p = custom[val];
      if (!p) return;

      const snapshot = getCurrentStylingSnapshot();
      p.styling = snapshot;
      p.updated_at = new Date().toISOString();
      custom[val] = p;
      setCustomPresets(custom);
      showPresetStatus(`Updated preset "${p.name}"!`);
      const fileSlug = p.slug || val.replace(/^custom_/, "");
      persistPresetToBackend(fileSlug, p.name, snapshot);
    });
  }

  // Save New Preset Trigger
  if (btnSavePreset && presetNameDrawer) {
    btnSavePreset.addEventListener("click", () => {
      presetDrawerMode = "save";
      if (drawerTitle) drawerTitle.textContent = "Save New Preset";
      if (btnConfirmPresetName) btnConfirmPresetName.textContent = "Save";
      if (presetNameInput) {
        presetNameInput.value = "";
        presetNameInput.placeholder = "Enter preset name (e.g. TikTok Yellow Pop)";
      }
      presetNameDrawer.style.display = "block";
      setTimeout(() => { if (presetNameInput) presetNameInput.focus(); }, 50);
    });
  }

  // Rename Preset Trigger
  if (btnRenamePreset && presetNameDrawer) {
    btnRenamePreset.addEventListener("click", () => {
      const val = selectPreset.value;
      if (!val || !val.startsWith("custom_")) return;
      const custom = getCustomPresets();
      const p = custom[val];
      if (!p) return;

      presetDrawerMode = "rename";
      if (drawerTitle) drawerTitle.textContent = `Rename Preset: "${p.name}"`;
      if (btnConfirmPresetName) btnConfirmPresetName.textContent = "Rename";
      if (presetNameInput) {
        presetNameInput.value = p.name;
      }
      presetNameDrawer.style.display = "block";
      setTimeout(() => {
        if (presetNameInput) {
          presetNameInput.focus();
          presetNameInput.select();
        }
      }, 50);
    });
  }

  // Confirm Name / Rename / Export
  if (btnConfirmPresetName) {
    btnConfirmPresetName.addEventListener("click", () => {
      const name = (presetNameInput ? presetNameInput.value.trim() : "");
      if (!name) {
        alert("Please enter a preset name.");
        return;
      }

      const custom = getCustomPresets();

      if (presetDrawerMode === "save") {
        const fileSlug = name.toLowerCase().replace(/[^a-z0-9_-]/g, "_").replace(/_+/g, "_").replace(/^_+|_+$/g, "") || ("preset_" + Date.now());
        const id = "custom_" + fileSlug;
        const snapshot = getCurrentStylingSnapshot();
        custom[id] = {
          id: id,
          name: name,
          slug: fileSlug,
          updated_at: new Date().toISOString(),
          styling: snapshot
        };
        setCustomPresets(custom);
        populatePresetDropdown(id);
        localStorage.setItem(PRESET_LAST_ACTIVE_KEY, id);
        showPresetStatus(`Preset "${name}" saved!`);
        persistPresetToBackend(fileSlug, name, snapshot);
      } else if (presetDrawerMode === "rename") {
        const id = selectPreset.value;
        if (id && custom[id]) {
          custom[id].name = name;
          custom[id].updated_at = new Date().toISOString();
          const slug = custom[id].slug || id.replace(/^custom_/, "");
          setCustomPresets(custom);
          populatePresetDropdown(id);
          showPresetStatus(`Preset renamed to "${name}"!`);
          persistPresetToBackend(slug, name, custom[id].styling);
        }
      } else if (presetDrawerMode === "export") {
        const cleanName = name.replace(/^[🔥🏷️🎬✨★\s]+/, "").trim() || "Custom Preset";
        const fileSlug = cleanName.toLowerCase().replace(/[^a-z0-9_-]/g, "_").replace(/_+/g, "_").replace(/^_+|_+$/g, "") || "preset";
        const stylingData = getCurrentStylingSnapshot();

        const payload = {
          name: cleanName,
          version: "1.0",
          exported_at: new Date().toISOString(),
          styling: stylingData
        };

        const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(payload, null, 2));
        const downloadAnchor = document.createElement("a");
        downloadAnchor.setAttribute("href", dataStr);
        downloadAnchor.setAttribute("download", `${fileSlug}.json`);
        document.body.appendChild(downloadAnchor);
        downloadAnchor.click();
        downloadAnchor.remove();

        showPresetStatus(`Exported preset "${fileSlug}.json" (${cleanName})!`);
      }

      if (presetNameDrawer) presetNameDrawer.style.display = "none";
    });
  }

  // Enter key support in preset name input
  if (presetNameInput) {
    presetNameInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        if (btnConfirmPresetName) btnConfirmPresetName.click();
      } else if (e.key === "Escape") {
        if (btnDismissPresetName) btnDismissPresetName.click();
      }
    });
  }

  if (btnDismissPresetName) {
    btnDismissPresetName.addEventListener("click", () => {
      if (presetNameDrawer) presetNameDrawer.style.display = "none";
    });
  }

  if (btnCancelPresetName) {
    btnCancelPresetName.addEventListener("click", () => {
      if (presetNameDrawer) presetNameDrawer.style.display = "none";
    });
  }

  // Delete Preset Trigger
  if (btnDeletePreset) {
    btnDeletePreset.addEventListener("click", () => {
      const id = selectPreset.value;
      if (!id || !id.startsWith("custom_")) return;
      const custom = getCustomPresets();
      const p = custom[id];
      if (!p) return;

      if (confirm(`Are you sure you want to delete preset "${p.name}"?`)) {
        const slug = p.slug || id.replace(/^custom_/, "");
        delete custom[id];
        setCustomPresets(custom);
        populatePresetDropdown("factory:tiktok_pop");
        loadAndApplyPreset("factory:tiktok_pop");
        showPresetStatus(`Preset "${p.name}" deleted.`);
        deletePresetFromBackend(slug);
      }
    });
  }

  // Export Preset (.json)
  if (btnExportPreset && presetNameDrawer) {
    btnExportPreset.addEventListener("click", () => {
      presetDrawerMode = "export";
      if (drawerTitle) drawerTitle.textContent = "Export Preset as JSON";
      if (btnConfirmPresetName) btnConfirmPresetName.textContent = "Export";

      const val = selectPreset ? selectPreset.value : "";
      let defaultName = "My Custom Preset";

      if (val && val.startsWith("custom_")) {
        const custom = getCustomPresets();
        if (custom[val] && custom[val].name) {
          defaultName = custom[val].name;
        }
      } else if (val && val.startsWith("factory:")) {
        const f = FACTORY_PRESETS[val];
        if (f && f.name) {
          defaultName = f.name.replace(/^[🔥🏷️🎬✨★\s]+/, "").trim();
        }
      }

      if (presetNameInput) {
        presetNameInput.value = defaultName;
        presetNameInput.placeholder = "Enter export preset name";
      }
      presetNameDrawer.style.display = "block";
      setTimeout(() => {
        if (presetNameInput) {
          presetNameInput.focus();
          presetNameInput.select();
        }
      }, 50);
    });
  }

  // Import Preset (.json)
  if (btnImportPresetTrigger && presetFileInput) {
    btnImportPresetTrigger.addEventListener("click", () => {
      presetFileInput.click();
    });

    presetFileInput.addEventListener("change", (e) => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;

      const reader = new FileReader();
      reader.onload = (event) => {
        try {
          const parsed = JSON.parse(event.target.result);
          if (!parsed || !parsed.styling) {
            alert("Invalid preset file format: missing 'styling' object.");
            return;
          }

          const fileBaseName = file.name.replace(/\.json$/i, "").trim();
          const isGenericName = (n) => !n || /^(voice_highlighter_preset|imported_preset|preset|custom_preset)$/i.test(n.trim());

          let cleanName = "";
          // If parsed.name is meaningful and not generic, use it;
          // If parsed.name is generic, check if the file was renamed on disk;
          // Otherwise fall back to parsed.name or fileBaseName.
          if (parsed.name && !isGenericName(parsed.name)) {
            cleanName = parsed.name;
          } else if (fileBaseName && !isGenericName(fileBaseName)) {
            cleanName = fileBaseName;
          } else {
            cleanName = parsed.name || fileBaseName || "Imported Preset";
          }

          cleanName = cleanName.replace(/^[🔥🏷️🎬✨★\s]+/, "").trim() || "Imported Preset";

          const custom = getCustomPresets();
          const id = "custom_" + Date.now();
          custom[id] = {
            id: id,
            name: cleanName,
            updated_at: new Date().toISOString(),
            styling: parsed.styling
          };

          setCustomPresets(custom);
          populatePresetDropdown(id);
          state.basePresetStyling = JSON.parse(JSON.stringify(parsed.styling));
          applyPresetStyling(parsed.styling);
          localStorage.setItem(PRESET_LAST_ACTIVE_KEY, id);
          showPresetStatus(`Imported & applied preset "${cleanName}"!`);
          const fileSlug = cleanName.toLowerCase().replace(/[^a-z0-9_-]/g, "_").replace(/_+/g, "_").replace(/^_+|_+$/g, "") || ("preset_" + Date.now());
          persistPresetToBackend(fileSlug, cleanName, parsed.styling);
        } catch (err) {
          alert(`Failed to parse preset JSON file: ${err.message}`);
        }
      };
      reader.readAsText(file);
      presetFileInput.value = "";
    });
  }

  // =========================================
  // SUBTITLE FILE & EXTERNAL EDITOR HUB
  // =========================================
  const btnEditAssResults = document.getElementById("btnEditAssResults");

  // Synchronize and display the active .ass file info directly from disk
  async function refreshAssFileInfo(options = {}) {
    let filePath = options.filePath || state.existingAssPath;
    let taskId = options.taskId || state.currentTaskId;
    let mediaPath = options.mediaPath || state.videoPath;

    if (!filePath && !taskId && !mediaPath) {
      updateAssHubUIEmpty();
      return;
    }

    try {
      const queryParams = [];
      if (filePath) queryParams.push(`path=${encodeURIComponent(filePath)}`);
      if (taskId) queryParams.push(`task_id=${encodeURIComponent(taskId)}`);
      if (mediaPath) queryParams.push(`media_path=${encodeURIComponent(mediaPath)}`);

      const res = await fetch(`/api/ass-file-info?${queryParams.join('&')}`);
      if (!res.ok) {
        if (!options.silent) updateAssHubUIEmpty();
        return;
      }
      const data = await res.json();
      state.existingAssPath = data.path;
      state.hasExistingAss = true;
      state.existingAssName = data.filename;

      updateAssHubUIPopulated(data);

      // Also refresh stage preview dialogue so interactive canvas is updated
      loadDialogueTranscriptForStage({ taskId, mediaPath, assPath: data.path });
    } catch (err) {
      console.warn("Could not refresh ASS file info from disk:", err);
      if (!options.silent) updateAssHubUIEmpty();
    }
  }

  function updateAssHubUIEmpty() {
    if (assFileStatusBadge) {
      assFileStatusBadge.textContent = "No .ass file loaded";
      assFileStatusBadge.className = "ass-file-status-badge";
    }
    if (assFilenameDisplay) assFilenameDisplay.textContent = "No subtitle file generated";
    if (assFilePathDisplay) assFilePathDisplay.textContent = 'Load a video or click "Generate Subtitles" to create .ass file';
    if (assDialogueCountDisplay) assDialogueCountDisplay.textContent = "—";
    if (assFileSizeDisplay) assFileSizeDisplay.textContent = "—";
    if (assMtimeDisplay) assMtimeDisplay.textContent = "—";
    if (chipStep2Count) chipStep2Count.textContent = "0 lines";

    if (btnOpenInTextEditor) btnOpenInTextEditor.disabled = true;
    if (btnShowInFileManager) btnShowInFileManager.disabled = true;
    if (btnCopyAssPath) btnCopyAssPath.disabled = true;
    if (btnRefreshAssFromDisk) btnRefreshAssFromDisk.disabled = true;
  }

  function updateAssHubUIPopulated(info) {
    if (assFileStatusBadge) {
      assFileStatusBadge.textContent = "Ready on Disk";
      assFileStatusBadge.className = "ass-file-status-badge badge-ready";
    }
    if (assFilenameDisplay) assFilenameDisplay.textContent = info.filename || "subtitles.ass";
    if (assFilePathDisplay) assFilePathDisplay.textContent = info.path || "";
    if (assDialogueCountDisplay) assDialogueCountDisplay.textContent = `${info.dialogue_count || 0} lines`;
    if (assFileSizeDisplay) assFileSizeDisplay.textContent = `${info.size_kb || 0} KB`;

    if (info.mtime && assMtimeDisplay) {
      const date = new Date(info.mtime * 1000);
      assMtimeDisplay.textContent = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }
    if (chipStep2Count) {
      chipStep2Count.textContent = `${info.dialogue_count || 0} lines`;
    }

    if (btnOpenInTextEditor) btnOpenInTextEditor.disabled = false;
    if (btnShowInFileManager) btnShowInFileManager.disabled = false;
    if (btnCopyAssPath) btnCopyAssPath.disabled = false;
    if (btnRefreshAssFromDisk) btnRefreshAssFromDisk.disabled = false;

    updateWorkflowStepper('subtitles_ready');
    if (btnBurnOnly) btnBurnOnly.classList.remove('disabled');
  }

  async function loadDialogueTranscriptForStage(options = {}) {
    let taskId = options.taskId || state.currentTaskId;
    let mediaPath = options.mediaPath || state.videoPath || "";
    let assPath = options.assPath || state.existingAssPath || "";

    try {
      let url = "";
      if (taskId) {
        url = `/api/ass-content/${encodeURIComponent(taskId)}`;
        if (mediaPath) url += `?media_path=${encodeURIComponent(mediaPath)}`;
      } else {
        url = `/api/ass-content?media_path=${encodeURIComponent(mediaPath)}`;
        if (assPath) url += `&ass_path=${encodeURIComponent(assPath)}`;
      }

      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      state.dialogues = data.dialogues || [];

      if (data.speaker_samples) {
        state.speakerSamples = data.speaker_samples;
        updateSpeakerSampleUI();
      }

      const spkCount = data.speaker_count || (data.detected_speakers ? data.detected_speakers.length : 1);
      const isMulti = Boolean(data.is_multi_speaker || spkCount > 1);
      if (isMulti) {
        state.isMultiSpeaker = true;
        updateSpeakerControlsVisibility(spkCount, data.detected_speakers);
      } else {
        state.isMultiSpeaker = false;
        updateSpeakerControlsVisibility(1);
      }

      if (state.dialogues && state.dialogues.length > 0) {
        if (btnTextDefault) {
          btnTextDefault.disabled = false;
          btnTextDefault.classList.remove("disabled");
          btnTextDefault.title = "Preview subtitle text from dialogue";
        }
        if (state.dialogues[0].clean_text && (!state.previewText || state.previewText.startsWith("Lorem ipsum"))) {
          const cleanPhrase = state.dialogues[0].clean_text.replace(/\\N/gi, " ").replace(/\\h/gi, " ").replace(/\s+/g, " ").trim();
          state.previewText = cleanPhrase;
          if (previewTextInput) previewTextInput.value = cleanPhrase;
          if (btnTextDefault) {
            btnTextDefault.textContent = "Dialog Transcript";
            btnTextDefault.classList.add("active");
          }
          if (btnTextLorem) btnTextLorem.classList.remove("active");
          state.activeWordIndex = 0;
          renderSubtitlePreview();
        }
      }
    } catch (err) {
      console.warn("Could not load dialogue transcript for stage:", err);
    }
  }

  // ----------------------------------------------------
  // Studio Stepper Controller
  // ----------------------------------------------------
  function updateWorkflowStepper(stage) {
    if (!wfStep1 || !wfStep2 || !wfStep3) return;

    if (stage === 'idle') {
      wfStep1.className = 'wf-step active';
      wfStep2.className = 'wf-step';
      wfStep3.className = 'wf-step';
      if (chipPipelineStatus) {
        chipPipelineStatus.textContent = 'Ready for Subtitles';
        chipPipelineStatus.className = 'pipeline-chip';
      }
    } else if (stage === 'transcribing') {
      wfStep1.className = 'wf-step active';
      wfStep2.className = 'wf-step';
      wfStep3.className = 'wf-step';
      if (chipPipelineStatus) {
        chipPipelineStatus.textContent = 'Transcribing (WhisperX)...';
        chipPipelineStatus.className = 'pipeline-chip chip-busy';
      }
    } else if (stage === 'subtitles_ready') {
      wfStep1.className = 'wf-step completed';
      wfStep2.className = 'wf-step active';
      wfStep3.className = 'wf-step';
      const count = (state.dialogues ? state.dialogues.length : 0);
      if (chipPipelineStatus) {
        chipPipelineStatus.textContent = count > 0 ? `Subtitles Ready (${count} lines)` : 'Subtitles Ready';
        chipPipelineStatus.className = 'pipeline-chip chip-success';
      }
      if (btnBurnOnly) {
        btnBurnOnly.classList.remove('disabled');
        btnBurnOnly.title = 'Click to burn subtitles into video with GPU NVENC';
      }
      if (titleGenerateAss) titleGenerateAss.textContent = 'Re-Transcribe Subtitles (.ass format)';
      if (descGenerateAss) descGenerateAss.textContent = 'Generate text from speech. Open in editor or file manager in Step 2.';
    } else if (stage === 'burning') {
      wfStep1.className = 'wf-step completed';
      wfStep2.className = 'wf-step completed';
      wfStep3.className = 'wf-step active';
      if (chipPipelineStatus) {
        chipPipelineStatus.textContent = 'Burning Video (NVENC)...';
        chipPipelineStatus.className = 'pipeline-chip chip-busy';
      }
    } else if (stage === 'burned') {
      wfStep1.className = 'wf-step completed';
      wfStep2.className = 'wf-step completed';
      wfStep3.className = 'wf-step completed';
      if (chipPipelineStatus) {
        chipPipelineStatus.textContent = 'Burned Video Ready (.mp4)';
        chipPipelineStatus.className = 'pipeline-chip chip-success';
      }
      if (btnBurnOnly) {
        btnBurnOnly.classList.remove('disabled');
      }
    }
  }

  // ----------------------------------------------------
  // External Text Editor & File Manager Actions
  // ----------------------------------------------------
  if (btnOpenInTextEditor) {
    btnOpenInTextEditor.addEventListener("click", async () => {
      const target = state.existingAssPath;
      if (!target) {
        alert("No .ass subtitle file available on disk yet.\n\nPlease generate subtitles first in Step 1.");
        return;
      }
      try {
        btnOpenInTextEditor.disabled = true;
        const origHtml = btnOpenInTextEditor.innerHTML;
        btnOpenInTextEditor.innerHTML = `<svg class="spin-icon" viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle></svg> Opening editor...`;

        const res = await fetch("/api/open-file", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ file_path: target, task_id: state.currentTaskId, media_path: state.videoPath })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to launch text editor");

        btnOpenInTextEditor.innerHTML = `✓ Opened in Text Editor!`;
        setTimeout(() => {
          btnOpenInTextEditor.innerHTML = origHtml;
          btnOpenInTextEditor.disabled = false;
        }, 2200);
      } catch (err) {
        alert(`Could not launch default text editor:\n${err.message}`);
        btnOpenInTextEditor.disabled = false;
        btnOpenInTextEditor.innerHTML = `<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg> <span>Open in Text Editor</span>`;
      }
    });
  }

  if (btnShowInFileManager) {
    btnShowInFileManager.addEventListener("click", async () => {
      const target = state.existingAssPath;
      if (!target) {
        alert("No .ass subtitle file available on disk yet.\n\nPlease generate subtitles first in Step 1.");
        return;
      }
      try {
        btnShowInFileManager.disabled = true;
        const origHtml = btnShowInFileManager.innerHTML;
        btnShowInFileManager.innerHTML = `<svg class="spin-icon" viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle></svg> Opening folder...`;

        const res = await fetch("/api/open-folder", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ file_path: target, task_id: state.currentTaskId, media_path: state.videoPath })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to launch file manager");

        btnShowInFileManager.innerHTML = `✓ Opened in File Manager!`;
        setTimeout(() => {
          btnShowInFileManager.innerHTML = origHtml;
          btnShowInFileManager.disabled = false;
        }, 2200);
      } catch (err) {
        alert(`Could not launch file manager:\n${err.message}`);
        btnShowInFileManager.disabled = false;
        btnShowInFileManager.innerHTML = `<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg> <span>Show in File Manager</span>`;
      }
    });
  }

  if (btnCopyAssPath) {
    btnCopyAssPath.addEventListener("click", () => {
      const target = state.existingAssPath;
      if (!target) return;
      navigator.clipboard.writeText(target).then(() => {
        const origHtml = btnCopyAssPath.innerHTML;
        btnCopyAssPath.innerHTML = `✓ Path Copied!`;
        setTimeout(() => {
          btnCopyAssPath.innerHTML = origHtml;
        }, 2000);
      });
    });
  }

  if (btnRefreshAssFromDisk) {
    btnRefreshAssFromDisk.addEventListener("click", async () => {
      const origHtml = btnRefreshAssFromDisk.innerHTML;
      btnRefreshAssFromDisk.innerHTML = `<svg class="spin-icon" viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle></svg> Checking disk...`;
      await refreshAssFileInfo({ filePath: state.existingAssPath, taskId: state.currentTaskId, mediaPath: state.videoPath });
      btnRefreshAssFromDisk.innerHTML = `✓ Reloaded from Disk!`;
      setTimeout(() => {
        btnRefreshAssFromDisk.innerHTML = origHtml;
      }, 1800);
    });
  }

  if (btnFocusStep2) {
    btnFocusStep2.addEventListener("click", () => {
      if (cardAssFileHub) {
        cardAssFileHub.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    });
  }

  if (btnEditAssResults) {
    btnEditAssResults.addEventListener("click", () => {
      if (btnOpenInTextEditor && !btnOpenInTextEditor.disabled) {
        btnOpenInTextEditor.click();
      } else if (cardAssFileHub) {
        cardAssFileHub.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    });
  }

  if (btnOpenVideo) {
    btnOpenVideo.addEventListener("click", async () => {
      const targetVideo = state.lastBurnedVideoPath || state.videoPath;
      if (!targetVideo) {
        alert("No burned video available to open yet.");
        return;
      }
      try {
        btnOpenVideo.disabled = true;
        const origHtml = btnOpenVideo.innerHTML;
        btnOpenVideo.innerHTML = `<svg class="spin-icon" viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2.2" fill="none"><circle cx="12" cy="12" r="10"></circle></svg> Launching player...`;
        const res = await fetch("/api/open-video", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            video_path: targetVideo,
            task_id: state.currentTaskId
          })
        });
        const respData = await res.json();
        if (!res.ok) {
          throw new Error(respData.detail || "Failed to open video in player");
        }
        btnOpenVideo.innerHTML = `<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2.5" fill="none"><polyline points="20 6 9 17 4 12"></polyline></svg> Opened in Default Player!`;
        setTimeout(() => {
          btnOpenVideo.innerHTML = origHtml;
          btnOpenVideo.disabled = false;
        }, 2500);
      } catch (err) {
        alert(`Could not launch default player:\n${err.message}`);
        btnOpenVideo.disabled = false;
        btnOpenVideo.innerHTML = `<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2.2" fill="none"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg> <span>Open in Default Player</span>`;
      }
    });
  }

  if (btnCopyBurnedPath) {
    btnCopyBurnedPath.addEventListener("click", () => {
      const pathText = (burnedVideoPathText ? burnedVideoPathText.textContent : state.lastBurnedVideoPath) || "";
      if (pathText) {
        navigator.clipboard.writeText(pathText).then(() => {
          if (copyBurnedBtnText) copyBurnedBtnText.textContent = "Copied!";
          setTimeout(() => {
            if (copyBurnedBtnText) copyBurnedBtnText.textContent = "Copy Path";
          }, 2000);
        });
      }
    });
  }

  // Initialize
  fetchSystemInfo();
  updatePosition(state.posX, state.posY, true);
  updateStageVisibility();
  renderSubtitlePreview();
  renderSocialOverlay();
  renderVocabChips();
  syncDeliverableFilenames();
  if (state.videoPath) {
    loadVideoInfo(state.videoPath);
  }

  // Initialize Presets from localStorage & sync from backend disk
  let savedActivePreset = localStorage.getItem(PRESET_LAST_ACTIVE_KEY) || "factory:tiktok_pop";
  if (!savedActivePreset) {
    savedActivePreset = "factory:tiktok_pop";
    localStorage.setItem(PRESET_LAST_ACTIVE_KEY, "factory:tiktok_pop");
  }
  populatePresetDropdown(savedActivePreset);
  loadAndApplyPreset(savedActivePreset);
  syncPresetsFromBackend();
});
