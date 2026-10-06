import Quickshell

ShellRoot {
    Variants {
        model: Quickshell.screens
        IslandBar {
            required property var modelData
            screen: modelData
        }
    }
}
