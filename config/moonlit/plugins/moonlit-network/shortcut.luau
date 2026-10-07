shortcut.setLabel("Network")
shortcut.setIcon("network")
shortcut.setActive(false)
function onClick() noctalia.togglePanel("dotfiles/moonlit-network:overview") end
function onRightClick() noctalia.runAsync({"noctalia", "msg", "panel-open", "control-center", "network"}) end
