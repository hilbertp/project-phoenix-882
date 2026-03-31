(function () {
  const state = {
    currentPosition: 1,
    totalStructures: 0,
    currentPayload: null,
    summaryPayload: null,
    viewing: "current",
    pendingAction: null,
    previousComparisonUsed: false,
    lastSubmission: null,
    chartReady: false,
    syncInFlight: false,
    syncFailed: false,
    syncFailureReason: "",
    tradingViewStatus: "Waiting to sync current structure.",
    liveReviewAnchors: null,
    liveReviewToolSource: null,
    liveReviewToolMatchesProposal: null,
    liveReviewToolReused: false,
    reviewNoteDraft: "",
    sessionTrail: [],
  };

  const VIEW_STATE_STORAGE_KEY = "db1-review-surface-state-v1";
  const restoredViewState = readPersistedViewState();

  state.currentPosition = restoredViewState.currentPosition || 1;
  state.viewing = restoredViewState.viewing || "current";
  state.previousComparisonUsed = Boolean(restoredViewState.previousComparisonUsed);
  state.reviewNoteDraft = restoredViewState.reviewNote || "";
  state.sessionTrail = Array.isArray(restoredViewState.sessionTrail)
    ? restoredViewState.sessionTrail
    : [];
  state.lastSubmission = state.sessionTrail.length > 0 ? state.sessionTrail[0] : null;

  const elements = {
    marketSymbol: document.getElementById("market-symbol"),
    progressLabel: document.getElementById("progress-label"),
    toggleState: document.getElementById("toggle-state"),
    showCurrentButton: document.getElementById("show-current-button"),
    showPreviousButton: document.getElementById("show-previous-button"),
    reloadButton: document.getElementById("reload-button"),
    syncChartButton: document.getElementById("sync-chart-button"),
    positionSummary: document.getElementById("position-summary"),
    statusBanner: document.getElementById("status-banner"),
    tradingViewStatus: document.getElementById("tradingview-status"),
    sessionSequencePosition: document.getElementById("session-sequence-position"),
    sessionPreviousAction: document.getElementById("session-previous-action"),
    sessionNextTarget: document.getElementById("session-next-target"),
    latestSubmissionHeading: document.getElementById("latest-submission-heading"),
    latestSubmissionStructure: document.getElementById("latest-submission-structure"),
    latestSubmissionOutcome: document.getElementById("latest-submission-outcome"),
    latestSubmissionNote: document.getElementById("latest-submission-note"),
    latestSubmissionTimestamp: document.getElementById("latest-submission-timestamp"),
    sessionTrailList: document.getElementById("session-trail-list"),
    summaryReadinessHint: document.getElementById("summary-readiness-hint"),
    summaryTotalReviewed: document.getElementById("summary-total-reviewed"),
    summaryGoodEnough: document.getElementById("summary-good-enough"),
    summaryAdjustedAccept: document.getElementById("summary-adjusted-accept"),
    summaryFlatoutWrong: document.getElementById("summary-flatout-wrong"),
    summaryPositiveShare: document.getElementById("summary-positive-share"),
    wrongCaseSummaryBlock: document.getElementById("wrong-case-summary-block"),
    wrongCaseReasonList: document.getElementById("wrong-case-reason-list"),
    marketContextTitle: document.getElementById("market-context-title"),
    marketContextSymbol: document.getElementById("market-context-symbol"),
    marketContextInstrument: document.getElementById("market-context-instrument"),
    marketContextTimeframe: document.getElementById("market-context-timeframe"),
    reviewTargetId: document.getElementById("review-target-id"),
    comparisonModeCopy: document.getElementById("comparison-mode-copy"),
    comparisonCard: document.getElementById("comparison-card"),
    comparisonModePill: document.getElementById("comparison-mode-pill"),
    structureId: document.getElementById("structure-id"),
    directionChip: document.getElementById("direction-chip"),
    viewingLabel: document.getElementById("viewing-label"),
    progressPosition: document.getElementById("progress-position"),
    previousAvailability: document.getElementById("previous-availability"),
    parentAnchorKind: document.getElementById("parent-anchor-kind"),
    parentAnchorPrice: document.getElementById("parent-anchor-price"),
    parentAnchorTimestamp: document.getElementById("parent-anchor-timestamp"),
    terminalExtremeKind: document.getElementById("terminal-extreme-kind"),
    terminalExtremePrice: document.getElementById("terminal-extreme-price"),
    terminalExtremeTimestamp: document.getElementById("terminal-extreme-timestamp"),
    anchorRangeLow: document.getElementById("anchor-range-low"),
    anchorRangeHigh: document.getElementById("anchor-range-high"),
    lifecycleState: document.getElementById("lifecycle-state"),
    pendingAction: document.getElementById("pending-action"),
    reviewNoteInput: document.getElementById("review-note-input"),
    goodEnoughButton: document.getElementById("good-enough-button"),
    adjustedAcceptButton: document.getElementById("adjusted-accept-button"),
    flatoutWrongButton: document.getElementById("flatout-wrong-button"),
    reviewLockReason: document.getElementById("review-lock-reason"),
    debugPayload: document.getElementById("debug-payload"),
  };

  const API_BASE_URL = window.DB1_REVIEW_API_BASE_URL || "http://127.0.0.1:8000";

  wireEvents();
  loadPosition(state.currentPosition, { preserveViewState: true, preserveNote: true });

  function wireEvents() {
    elements.showCurrentButton.addEventListener("click", function () {
      state.viewing = "current";
      persistViewState();
      render();
    });

    elements.showPreviousButton.addEventListener("click", function () {
      if (!hasPrevious()) {
        return;
      }
      state.viewing = "previous";
      state.previousComparisonUsed = true;
      persistViewState();
      render();
    });

    elements.reloadButton.addEventListener("click", function () {
      loadPosition(state.currentPosition, { preserveViewState: true, preserveNote: true });
    });

    elements.syncChartButton.addEventListener("click", function () {
      syncTradingViewCurrentStructure();
    });

    elements.goodEnoughButton.addEventListener("click", function () {
      finaliseAction("good_enough");
    });

    elements.flatoutWrongButton.addEventListener("click", function () {
      finaliseAction("flatout_wrong");
    });

    elements.adjustedAcceptButton.addEventListener("click", function () {
      finaliseAction("adjusted_accept");
    });

    elements.reviewNoteInput.addEventListener("input", function () {
      state.reviewNoteDraft = elements.reviewNoteInput.value;
      persistViewState();
    });

    document.addEventListener("keydown", handleKeyboardShortcut);
  }

  async function loadPosition(position, options) {
    const preserveViewState = Boolean(options && options.preserveViewState);
    const preserveNote = Boolean(options && options.preserveNote);
    setStatus("Loading review structure...");
    try {
      const response = await fetch(
        API_BASE_URL + "/db1/review/structures?position=" + String(position)
      );
      if (!response.ok) {
        const errorPayload = await response.json().catch(function () {
          return { error: "Request failed." };
        });
        throw new Error(errorPayload.error || "Request failed.");
      }
      state.currentPayload = await response.json();
      state.currentPosition = state.currentPayload.progress.current_position;
      state.totalStructures = state.currentPayload.progress.total_structures;
      if (!preserveViewState) {
        state.viewing = "current";
        state.previousComparisonUsed = false;
      }
      state.pendingAction = null;
      state.lastSubmission = state.sessionTrail.length > 0 ? state.sessionTrail[0] : null;
      state.chartReady = false;
      state.syncInFlight = false;
      state.syncFailed = false;
      state.syncFailureReason = "";
      state.liveReviewAnchors = null;
      state.liveReviewToolSource = null;
      state.liveReviewToolMatchesProposal = null;
      state.liveReviewToolReused = false;
      if (!preserveNote) {
        state.reviewNoteDraft = "";
      }
      if (state.viewing === "previous" && !state.currentPayload.previous_structure) {
        state.viewing = "current";
      }
      elements.reviewNoteInput.value = state.reviewNoteDraft;
      persistViewState();
      await loadSummary();
      setStatus("Loaded " + state.currentPayload.progress.label + ".");
      render();
      await syncTradingViewCurrentStructure();
      render();
    } catch (error) {
      setStatus(String(error.message || error), "error");
      render();
    }
  }

  async function loadSummary() {
    try {
      const response = await fetch(API_BASE_URL + "/db1/review/summary");
      if (!response.ok) {
        const errorPayload = await response.json().catch(function () {
          return { error: "Summary request failed." };
        });
        throw new Error(errorPayload.error || "Summary request failed.");
      }
      state.summaryPayload = await response.json();
    } catch (error) {
      state.summaryPayload = null;
      throw error;
    }
  }

  async function finaliseAction(action) {
    if (state.syncInFlight) {
      setStatus("TradingView sync is still in progress for the current structure.", "error");
      return;
    }

    if (!state.chartReady) {
      setStatus(
        "TradingView sync failed for the current structure. Re-sync before submitting a review.",
        "error"
      );
      return;
    }

    state.pendingAction = action;
    persistViewState();
    let submissionPayload;
    try {
      submissionPayload = buildSubmissionPayload(action);
    } catch (error) {
      state.pendingAction = null;
      setStatus(String(error.message || error), "error");
      persistViewState();
      render();
      return;
    }
    try {
      const response = await fetch(API_BASE_URL + "/db1/review/submissions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(submissionPayload),
      });

      if (!response.ok) {
        const errorPayload = await response.json().catch(function () {
          return { error: "Review submission failed." };
        });
        throw new Error(errorPayload.error || "Review submission failed.");
      }

      const responsePayload = await response.json();
      state.lastSubmission = createSessionTrailEntry(responsePayload, state.reviewNoteDraft);
      state.sessionTrail.unshift(state.lastSubmission);
      persistViewState();
      await loadSummary();
    } catch (error) {
      state.pendingAction = null;
      setStatus(String(error.message || error), "error");
      persistViewState();
      render();
      return;
    }

    const nextPosition = state.currentPosition + 1;
    if (nextPosition > state.totalStructures) {
      state.reviewNoteDraft = "";
      persistViewState();
      setStatus(
        "Review complete. Final action: " + action + ". Submission recorded.",
        "warning"
      );
      render();
      return;
    }

    setStatus("Finalised " + action + ". Submission recorded. Loading next structure...");
    state.reviewNoteDraft = "";
    await loadPosition(nextPosition, { preserveViewState: false, preserveNote: false });
  }

  function render() {
    if (!state.currentPayload) {
      return;
    }

    const structure = getVisibleStructure();
    const market = state.currentPayload.market_contract;
    const progress = state.currentPayload.progress;
    const summary = state.summaryPayload ? state.summaryPayload.summary : null;
    const reviewLocked =
      !state.chartReady || state.syncInFlight || state.pendingAction !== null;

    elements.marketSymbol.textContent = market.tradingview_symbol;
    elements.progressLabel.textContent = progress.label;
    elements.positionSummary.textContent =
      "current: " + progress.current_position + " / " + progress.total_structures;
    elements.marketContextTitle.textContent = market.human_label;
    elements.marketContextSymbol.textContent = market.tradingview_symbol;
    elements.marketContextInstrument.textContent = market.instrument_label;
    elements.marketContextTimeframe.textContent = market.timeframe;
    elements.reviewTargetId.textContent = state.currentPayload.current_structure.structure_id;
    elements.sessionSequencePosition.textContent =
      progress.current_position + " / " + progress.total_structures;
    elements.sessionNextTarget.textContent = state.currentPayload.current_structure.structure_id;

    elements.structureId.textContent = structure.structure_id;
    elements.directionChip.textContent = structure.direction;
    elements.viewingLabel.textContent = state.viewing;
    elements.progressPosition.textContent =
      progress.current_position + " / " + progress.total_structures;
    elements.previousAvailability.textContent = hasPrevious() ? "yes" : "no";

    elements.parentAnchorKind.textContent = structure.parent_anchor_kind;
    elements.parentAnchorPrice.textContent = formatPrice(structure.parent_anchor_price);
    elements.parentAnchorTimestamp.textContent = formatTimestamp(
      structure.parent_anchor_source_timestamp
    );

    elements.terminalExtremeKind.textContent = structure.terminal_extreme_kind;
    elements.terminalExtremePrice.textContent = formatPrice(
      structure.terminal_extreme_price
    );
    elements.terminalExtremeTimestamp.textContent = formatTimestamp(
      structure.terminal_extreme_source_timestamp
    );

    elements.anchorRangeLow.textContent = formatPrice(structure.anchor_range_low);
    elements.anchorRangeHigh.textContent = formatPrice(structure.anchor_range_high);
    elements.lifecycleState.textContent = structure.invalidation_reason
      ? "invalidated"
      : "active";
    elements.toggleState.textContent =
      state.viewing === "current"
        ? "Viewing current structure"
        : "Viewing previous structure";
    elements.pendingAction.textContent = state.pendingAction
      ? "Pending action: " + state.pendingAction
      : "No action selected";
    elements.tradingViewStatus.textContent = state.tradingViewStatus;
    elements.tradingViewStatus.classList.toggle("is-error", state.syncFailed);
    elements.syncChartButton.textContent = state.syncFailed
      ? "retry TradingView sync"
      : state.syncInFlight
        ? "syncing TradingView..."
        : "sync TradingView";
    renderSessionConfidence();
    renderComparisonState();
    renderReviewLockReason(reviewLocked);

    elements.showCurrentButton.classList.toggle(
      "is-active",
      state.viewing === "current"
    );
    elements.showPreviousButton.classList.toggle(
      "is-active",
      state.viewing === "previous"
    );
    elements.showPreviousButton.disabled = !hasPrevious() || state.pendingAction !== null;
    elements.syncChartButton.disabled = state.syncInFlight || state.pendingAction !== null;
    elements.goodEnoughButton.disabled = reviewLocked;
    elements.adjustedAcceptButton.disabled = reviewLocked;
    elements.flatoutWrongButton.disabled = reviewLocked;
    renderSummary(summary);
    elements.debugPayload.textContent = JSON.stringify(
      {
        progress: state.currentPayload.progress,
        current_structure: state.currentPayload.current_structure,
        previous_structure: state.currentPayload.previous_structure,
        summary: state.summaryPayload ? state.summaryPayload.summary : null,
        previous_structure_comparison_used: state.previousComparisonUsed,
        tradingview_status: state.tradingViewStatus,
        chart_ready: state.chartReady,
        sync_in_flight: state.syncInFlight,
        sync_failed: state.syncFailed,
        sync_failure_reason: state.syncFailureReason,
        live_review_anchors: state.liveReviewAnchors,
        live_review_tool_source: state.liveReviewToolSource,
        live_review_tool_matches_proposal: state.liveReviewToolMatchesProposal,
        live_review_tool_reused: state.liveReviewToolReused,
        review_note_draft: state.reviewNoteDraft,
        last_submission: state.lastSubmission,
      },
      null,
      2
    );
  }

  function buildSubmissionPayload(action) {
    const currentStructure = state.currentPayload.current_structure;
    const proposedAnchorPair = buildAnchorPairFromStructure(currentStructure);
    const adjustedAnchorPair = action === "adjusted_accept" ? state.liveReviewAnchors : null;

    if (action === "adjusted_accept" && !adjustedAnchorPair) {
      throw new Error(
        "TradingView sync did not return a live fib anchor pair for the current structure. Re-sync before submitting a meh review."
      );
    }

    return {
      structure_id: currentStructure.structure_id,
      proposed_anchor_pair: proposedAnchorPair,
      review_outcome: action,
      adjusted_anchor_pair: adjustedAnchorPair,
      note: state.reviewNoteDraft || null,
      previous_structure_comparison_used: state.previousComparisonUsed,
    };
  }

  function buildAnchorPairFromStructure(structure) {
    return {
      parent_anchor_source_timestamp: structure.parent_anchor_source_timestamp,
      parent_anchor_price: Number(structure.parent_anchor_price),
      terminal_extreme_source_timestamp: structure.terminal_extreme_source_timestamp,
      terminal_extreme_price: Number(structure.terminal_extreme_price),
    };
  }

  function renderSummary(summary) {
    if (!summary) {
      elements.summaryTotalReviewed.textContent = "-";
      elements.summaryGoodEnough.textContent = "-";
      elements.summaryAdjustedAccept.textContent = "-";
      elements.summaryFlatoutWrong.textContent = "-";
      elements.summaryPositiveShare.textContent = "-";
      elements.summaryReadinessHint.textContent = "summary unavailable";
      elements.summaryReadinessHint.classList.remove("is-continue", "is-kill");
      elements.wrongCaseSummaryBlock.classList.add("is-hidden");
      elements.wrongCaseReasonList.innerHTML = "";
      return;
    }

    elements.summaryTotalReviewed.textContent = String(
      summary.total_reviewed_structures
    );
    elements.summaryGoodEnough.textContent = String(summary.good_enough_count);
    elements.summaryAdjustedAccept.textContent = String(
      summary.adjusted_accept_count
    );
    elements.summaryFlatoutWrong.textContent = String(summary.flatout_wrong_count);
    elements.summaryPositiveShare.textContent = formatShare(
      summary.combined_positive_share
    );
    elements.summaryReadinessHint.textContent = summary.readiness_hint;
    elements.summaryReadinessHint.classList.toggle(
      "is-continue",
      summary.readiness_hint === "continue"
    );
    elements.summaryReadinessHint.classList.toggle(
      "is-kill",
      summary.readiness_hint === "kill and switch"
    );

    const reasonCounts = state.summaryPayload.wrong_case_reason_counts || [];
    elements.wrongCaseSummaryBlock.classList.toggle(
      "is-hidden",
      reasonCounts.length === 0
    );
    elements.wrongCaseReasonList.innerHTML = reasonCounts
      .map(function (reasonCount) {
        return "<li>" + reasonCount.reason + " (" + reasonCount.count + ")</li>";
      })
      .join("");
  }

  function renderSessionConfidence() {
    renderLatestSubmission();
    renderSessionTrail();
    renderSessionContext();
  }

  function renderLatestSubmission() {
    if (!state.lastSubmission) {
      elements.latestSubmissionHeading.textContent = "No local submission yet";
      elements.latestSubmissionStructure.textContent = "-";
      elements.latestSubmissionOutcome.textContent = "-";
      elements.latestSubmissionNote.textContent = "-";
      elements.latestSubmissionTimestamp.textContent = "-";
      return;
    }

    elements.latestSubmissionHeading.textContent =
      "Recorded " + formatOutcomeDisplay(state.lastSubmission.reviewOutcome) + " for "
      + state.lastSubmission.structureId;
    elements.latestSubmissionStructure.textContent = state.lastSubmission.structureId;
    elements.latestSubmissionOutcome.textContent = formatOutcomeDisplay(
      state.lastSubmission.reviewOutcome
    );
    elements.latestSubmissionNote.textContent = formatNoteDisplay(state.lastSubmission);
    elements.latestSubmissionTimestamp.textContent = formatTimestamp(
      state.lastSubmission.recordedAtUtc
    );
  }

  function renderSessionTrail() {
    if (state.sessionTrail.length === 0) {
      elements.sessionTrailList.innerHTML =
        '<li class="session-trail-empty">No local submissions recorded in this session yet.</li>';
      return;
    }

    elements.sessionTrailList.innerHTML = state.sessionTrail
      .slice(0, 5)
      .map(function (entry) {
        return (
          '<li class="session-trail-item">'
          + '<p class="session-trail-line"><strong>'
          + entry.structureId
          + '</strong> - '
          + formatOutcomeDisplay(entry.reviewOutcome)
          + '</p>'
          + '<p class="session-trail-line">'
          + formatNoteDisplay(entry)
          + ' - '
          + formatTimestamp(entry.recordedAtUtc)
          + '</p>'
          + '</li>'
        );
      })
      .join("");
  }

  function renderSessionContext() {
    if (!state.lastSubmission) {
      elements.sessionPreviousAction.textContent =
        "No submission recorded in this session yet.";
      return;
    }

    elements.sessionPreviousAction.textContent =
      formatOutcomeDisplay(state.lastSubmission.reviewOutcome)
      + " submitted for "
      + state.lastSubmission.structureId
      + " ("
      + formatNoteDisplay(state.lastSubmission)
      + ") at "
      + formatTimestamp(state.lastSubmission.recordedAtUtc)
      + ".";
  }

  function getVisibleStructure() {
    if (state.viewing === "previous" && hasPrevious()) {
      return state.currentPayload.previous_structure;
    }
    return state.currentPayload.current_structure;
  }

  function hasPrevious() {
    return Boolean(
      state.currentPayload && state.currentPayload.previous_structure
    );
  }

  function formatPrice(value) {
    return Number(value).toFixed(2);
  }

  function formatTimestamp(value) {
    return String(value).replace("T", " ");
  }

  function formatShare(value) {
    return (Number(value) * 100).toFixed(1) + "%";
  }

  function formatOutcomeDisplay(value) {
    if (value === "good_enough") {
      return "okay (good_enough)";
    }
    if (value === "adjusted_accept") {
      return "meh (adjusted_accept)";
    }
    if (value === "flatout_wrong") {
      return "wtf (flatout_wrong)";
    }
    return String(value);
  }

  function formatNoteDisplay(entry) {
    if (entry.noteText) {
      return 'note: "' + entry.noteText + '"';
    }
    return entry.noteState;
  }

  async function syncTradingViewCurrentStructure() {
    if (!state.currentPayload) {
      return;
    }

    state.chartReady = false;
    state.syncInFlight = true;
    state.syncFailed = false;
    state.syncFailureReason = "";
    state.liveReviewAnchors = null;
    state.liveReviewToolSource = null;
    state.liveReviewToolMatchesProposal = null;
    state.liveReviewToolReused = false;
    state.tradingViewStatus = "Syncing the real TradingView chart...";
    render();
    try {
      const response = await fetch(API_BASE_URL + "/db1/review/tradingview/sync", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          keep_browser_open: true,
          preserve_review_context: true,
          market_contract: state.currentPayload.market_contract,
          review_structure: state.currentPayload.current_structure,
        }),
      });
      if (!response.ok) {
        const errorPayload = await response.json().catch(function () {
          return { error: "TradingView sync failed." };
        });
        throw new Error(errorPayload.error || "TradingView sync failed.");
      }

      const payload = await response.json();
      const reviewTool = payload.review_tool || null;
      const liveAnchorPair = normaliseAnchorPair(
        reviewTool && typeof reviewTool === "object" ? reviewTool.anchor_pair : null
      );
      if (!liveAnchorPair) {
        throw new Error(
          "TradingView sync did not return a live fib anchor pair for the current structure."
        );
      }

      state.chartReady = true;
      state.syncInFlight = false;
      state.syncFailed = false;
      state.liveReviewAnchors = liveAnchorPair;
      state.liveReviewToolSource =
        reviewTool && typeof reviewTool.source === "string"
          ? reviewTool.source
          : "proposal-render";
      state.liveReviewToolMatchesProposal = Boolean(
        reviewTool && reviewTool.matches_proposed_anchors !== false
      );
      state.liveReviewToolReused = Boolean(
        reviewTool && reviewTool.reused_existing_tool
      );
      state.tradingViewStatus =
        "TradingView synced for "
        + payload.structure_id
        + " on "
        + payload.market_symbol
        + " "
        + payload.timeframe
        + ". "
        + formatReviewToolStatus();
      persistViewState();
      render();
    } catch (error) {
      state.chartReady = false;
      state.syncInFlight = false;
      state.syncFailed = true;
      state.syncFailureReason = String(error.message || error);
      state.liveReviewAnchors = null;
      state.liveReviewToolSource = null;
      state.liveReviewToolMatchesProposal = null;
      state.liveReviewToolReused = false;
      state.tradingViewStatus =
        "TradingView sync failed: "
        + state.syncFailureReason
        + " Use 'retry TradingView sync' to retry the current structure.";
      setStatus(state.tradingViewStatus, "error");
      persistViewState();
      render();
    }
  }

  function handleKeyboardShortcut(event) {
    if (shouldIgnoreShortcutTarget(event.target) || event.defaultPrevented) {
      return;
    }

    if (event.metaKey || event.ctrlKey || event.altKey) {
      return;
    }

    const key = String(event.key || "").toLowerCase();
    if (key === "") {
      return;
    }

    if (key === "o") {
      triggerShortcutAction(elements.goodEnoughButton, "good_enough");
      event.preventDefault();
      return;
    }

    if (key === "m") {
      triggerShortcutAction(elements.adjustedAcceptButton, "adjusted_accept");
      event.preventDefault();
      return;
    }

    if (key === "w") {
      triggerShortcutAction(elements.flatoutWrongButton, "flatout_wrong");
      event.preventDefault();
      return;
    }

    if (key === "v") {
      toggleComparisonView();
      event.preventDefault();
      return;
    }

    if (key === "r") {
      if (!elements.syncChartButton.disabled) {
        syncTradingViewCurrentStructure();
      }
      event.preventDefault();
    }
  }

  function triggerShortcutAction(button, action) {
    if (button.disabled) {
      return;
    }

    finaliseAction(action);
  }

  function toggleComparisonView() {
    if (!state.currentPayload || state.pendingAction !== null || !hasPrevious()) {
      return;
    }

    state.viewing = state.viewing === "current" ? "previous" : "current";
    if (state.viewing === "previous") {
      state.previousComparisonUsed = true;
    }
    persistViewState();
    render();
  }

  function shouldIgnoreShortcutTarget(target) {
    if (!target || !(target instanceof HTMLElement)) {
      return false;
    }

    const tagName = target.tagName.toLowerCase();
    return (
      tagName === "input"
      || tagName === "textarea"
      || tagName === "select"
      || target.isContentEditable
    );
  }

  function renderComparisonState() {
    const isPreviousView = state.viewing === "previous";
    elements.comparisonModePill.textContent = isPreviousView
      ? "previous comparison"
      : "current view";
    elements.comparisonModePill.classList.toggle("is-previous-view", isPreviousView);
    elements.comparisonModePill.classList.toggle("is-current-view", !isPreviousView);
    elements.comparisonCard.classList.toggle("is-previous-view", isPreviousView);
    elements.comparisonCard.classList.toggle("is-current-view", !isPreviousView);
    elements.comparisonModeCopy.textContent = isPreviousView
      ? "Judging "
        + state.currentPayload.current_structure.structure_id
        + " while comparing the previous structure on screen."
      : "Judging "
        + state.currentPayload.current_structure.structure_id
        + " with the current structure on screen.";
  }

  function renderReviewLockReason(reviewLocked) {
    const reason = getReviewLockReason(reviewLocked);
    elements.reviewLockReason.textContent = reason;
    elements.reviewLockReason.classList.toggle("is-error", reviewLocked);
    elements.reviewLockReason.classList.toggle("is-ready", !reviewLocked);
  }

  function getReviewLockReason(reviewLocked) {
    if (!reviewLocked) {
      return "Review actions enabled for the current structure.";
    }

    if (state.pendingAction !== null) {
      return "Review actions disabled: review submission is in progress.";
    }

    if (state.syncInFlight) {
      return "Review actions disabled: TradingView sync is in progress for the current structure.";
    }

    if (state.syncFailed) {
      return "Review actions disabled: " + state.syncFailureReason + " Retry TradingView sync for the current structure.";
    }

    return "Review actions disabled until TradingView sync completes for the current structure.";
  }

  function persistViewState() {
    try {
      window.sessionStorage.setItem(
        VIEW_STATE_STORAGE_KEY,
        JSON.stringify({
          currentPosition: state.currentPosition,
          viewing: state.viewing,
          previousComparisonUsed: state.previousComparisonUsed,
          reviewNote: state.reviewNoteDraft,
          sessionTrail: state.sessionTrail,
        })
      );
    } catch (error) {
      // Ignore storage failures; resilience falls back to in-memory state only.
    }
  }

  function readPersistedViewState() {
    try {
      const rawValue = window.sessionStorage.getItem(VIEW_STATE_STORAGE_KEY);
      if (!rawValue) {
        return {};
      }

      const payload = JSON.parse(rawValue);
      if (!payload || typeof payload !== "object") {
        return {};
      }

      return {
        currentPosition:
          typeof payload.currentPosition === "number" && payload.currentPosition > 0
            ? payload.currentPosition
            : 1,
        viewing: payload.viewing === "previous" ? "previous" : "current",
        previousComparisonUsed: Boolean(payload.previousComparisonUsed),
        reviewNote: typeof payload.reviewNote === "string" ? payload.reviewNote : "",
        sessionTrail: Array.isArray(payload.sessionTrail) ? payload.sessionTrail : [],
      };
    } catch (error) {
      return {};
    }
  }

  function createSessionTrailEntry(responsePayload, noteDraft) {
    const trimmedNote = typeof noteDraft === "string" ? noteDraft.trim() : "";

    return {
      submissionId: responsePayload.submission_id || "",
      structureId: responsePayload.structure_id || "",
      reviewOutcome: responsePayload.review_outcome || "",
      recordedAtUtc: responsePayload.recorded_at_utc || "",
      noteState: trimmedNote !== "" ? "note provided" : "no note",
      noteText: trimmedNote,
    };
  }

  function setStatus(message, tone) {
    elements.statusBanner.textContent = message;
    elements.statusBanner.classList.remove("is-warning", "is-error");
    if (tone === "warning") {
      elements.statusBanner.classList.add("is-warning");
    }
    if (tone === "error") {
      elements.statusBanner.classList.add("is-error");
    }
  }

  function normaliseAnchorPair(value) {
    if (!value || typeof value !== "object") {
      return null;
    }

    const parentAnchorSourceTimestamp = value.parent_anchor_source_timestamp;
    const parentAnchorPrice = value.parent_anchor_price;
    const terminalExtremeSourceTimestamp = value.terminal_extreme_source_timestamp;
    const terminalExtremePrice = value.terminal_extreme_price;
    if (
      typeof parentAnchorSourceTimestamp !== "string"
      || typeof terminalExtremeSourceTimestamp !== "string"
      || typeof parentAnchorPrice !== "number"
      || typeof terminalExtremePrice !== "number"
    ) {
      return null;
    }

    return {
      parent_anchor_source_timestamp: parentAnchorSourceTimestamp,
      parent_anchor_price: parentAnchorPrice,
      terminal_extreme_source_timestamp: terminalExtremeSourceTimestamp,
      terminal_extreme_price: terminalExtremePrice,
    };
  }

  function formatReviewToolStatus() {
    if (!state.liveReviewAnchors) {
      return "";
    }

    if (state.liveReviewToolReused && state.liveReviewToolMatchesProposal === false) {
      return "Live fib preserved with reviewer-adjusted anchors.";
    }

    if (state.liveReviewToolReused) {
      return "Live fib preserved for continued review edits.";
    }

    return "Proposal fib placed and ready for review edits.";
  }
})();