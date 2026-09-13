from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_failure_owner_adopts_browse_wrappers_without_replacing_policy():
    recovery = text("architecture/playback-early-pause-recovery-v538.js")
    browse = text("ui/browse-curated-programming-v537.js")

    # Browse keeps its existing compatibility policy, including same-game
    # alternate/next-game behavior. The architecture layer adopts that completed
    # chain instead of rewriting the policy in a second place.
    assert "function patchPlaybackFailure()" in browse
    assert "function patchYouTubePlayerError()" in browse
    assert "__sbbBrowseV5313" in browse
    assert "__sbbBrowseV5314" in browse

    for token in [
        "function installFailureOwnership()",
        "window.SBB_PLAYBACK_FAILURE_OWNER",
        "__sbbPlaybackFailureOwner",
        "owned.__sbbOwnershipP1=true",
        "owned.__sbbBrowseV5313=true",
        "owned.__sbbBrowseV5314=true",
        "owned.__sbbOriginal=current.__sbbOriginal||current",
        "owned.__sbbAdopted=current",
        "failureOwnershipSnapshot",
    ]:
        assert token in recovery

    # Never seize the original app callbacks before Browse has installed its
    # curated policy. The owner only adopts callbacks carrying Browse's marker.
    assert "else if(current?.__sbbBrowseV5313)" in recovery
    assert "else if(current?.__sbbBrowseV5314)" in recovery

    # Browse has delayed patch retries. Architecture ownership preserves those
    # markers so the retries observe an already-patched callback rather than
    # constructing another wrapper layer.
    assert "for(const ms of [80,700,1400])setTimeout(installFailureOwnership,ms)" in recovery


def test_failure_owner_loads_after_browse_and_activation_adapter_stays_nonrecursive():
    index = text("index.html")
    app = text("app.js")

    browse_tag = '<script src="ui/browse-curated-programming-v537.js?v=5.5.0"></script>'
    owner_tag = '<script src="architecture/playback-early-pause-recovery-v538.js?v=5.5.0"></script>'
    assert browse_tag in index
    assert owner_tag in index
    assert index.index(browse_tag) < index.index(owner_tag)

    # The orchestrator adapter closes over PlaybackController directly, not the
    # public tuneProgramIndexV5 facade. Extending architecture ownership therefore
    # cannot create a tune -> adapter -> tune recursion loop.
    assert "tuneProgramIndex:(index,options)=>PlaybackController.tuneProgramIndex(index,options)" in app
    assert "window.SBB_PLAYBACK_CONTROLLER=PlaybackController" in app
