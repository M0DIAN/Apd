import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1000
    height: 760
    minimumWidth: 850
    minimumHeight: 600
    visible: true
    title: "APD 多模型开发监视器"
    color: "#0d121c"
    property var info: monitor.data
    property color accent: info.failed ? "#f38d99" : "#70dec9"
    font.family: Qt.platform.os === "windows" ? "Microsoft YaHei UI" : "sans-serif"

    component Caption: Text {
        color: "#8999b1"
        font.pixelSize: 12
        textFormat: Text.PlainText
    }
    component Value: Text {
        color: "#dfe7f2"
        font.pixelSize: 13
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
        Layout.fillWidth: true
    }
    component Field: ColumnLayout {
        property string label
        property string value
        spacing: 5
        Layout.fillWidth: true
        Caption { text: parent.label }
        Value { text: parent.value }
    }
    component Panel: Rectangle {
        property string heading
        default property alias contents: body.data
        color: "#161e2b"
        radius: 14
        border.color: "#273449"
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignTop
        implicitHeight: body.implicitHeight + 32
        ColumnLayout {
            id: body
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 16 }
            spacing: 13
            Text {
                text: parent.parent.heading
                color: "#dfe7f2"
                font { pixelSize: 14; bold: true }
            }
        }
    }

    ScrollView {
        id: scroll
        anchors.fill: parent
        anchors.margins: 24
        contentWidth: availableWidth
        clip: true
        ColumnLayout {
            width: scroll.availableWidth
            spacing: 16

            RowLayout {
                Layout.fillWidth: true
                ColumnLayout {
                    spacing: 7
                    Text { text: "APD 多模型开发监视器"; color: "#f2f6fc"; font { pixelSize: 24; bold: true } }
                    Caption { text: window.info.waiting }
                }
                Item { Layout.fillWidth: true }
                Rectangle {
                    implicitWidth: statusLabel.implicitWidth + 38
                    implicitHeight: 34
                    radius: 17
                    color: "#202f36"
                    border.color: window.accent
                    Text { id: statusLabel; anchors.centerIn: parent; text: "●  " + window.info.status; color: window.accent; font.pixelSize: 13 }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Caption { text: "项目  " + window.info.repo; elide: Text.ElideMiddle; Layout.fillWidth: true }
                Caption { text: "Canonical State  v" + window.info.version; color: window.accent }
            }

            Panel {
                heading: "当前任务"
                Value { text: window.info.task; font.pixelSize: 15 }
                RowLayout {
                    Layout.fillWidth: true
                    Field { label: "任务类型"; value: window.info.taskType }
                    Field { label: "权限"; value: window.info.permission }
                    Field { label: "当前阶段"; value: window.info.stage }
                }
                Value { visible: text.length > 0; text: window.info.error; color: "#f38d99" }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                Repeater {
                    model: window.info.sessions
                    delegate: Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: 158
                        radius: 14
                        color: modelData.active ? "#19332f" : "#161e2b"
                        border { color: modelData.active ? window.accent : "#273449"; width: modelData.active ? 2 : 1 }
                        Behavior on color { ColorAnimation { duration: 220 } }
                        ColumnLayout {
                            anchors { fill: parent; margins: 16 }
                            spacing: 7
                            RowLayout {
                                Layout.fillWidth: true
                                Text { text: modelData.name; color: "#f2f6fc"; font { pixelSize: 19; bold: true } }
                                Item { Layout.fillWidth: true }
                                Text {
                                    text: modelData.status
                                    color: modelData.active || modelData.result === "PASS" ? "#70dec9" :
                                           modelData.result === "FAIL" ? "#f38d99" :
                                           modelData.result === "BLOCKED" ? "#f2ca7b" : "#8999b1"
                                    font.pixelSize: 12
                                }
                            }
                            Caption { text: modelData.role }
                            Value { text: modelData.model; font.pixelSize: 12; elide: Text.ElideRight; maximumLineCount: 1 }
                            Caption { text: modelData.effort }
                            Item { Layout.fillHeight: true }
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                spacing: 12
                Panel {
                    heading: "Router / Session"
                    Layout.preferredWidth: 1
                    Field { label: "路由选择 · 模型 ID · 档位（请求）"; value: "→ " + window.info.route + "  /  " + window.info.model + "  /  " + window.info.effort }
                    Field { label: "Router 原因"; value: window.info.reason }
                    RowLayout {
                        Layout.fillWidth: true
                        Field { label: "Thread"; value: window.info.thread }
                        Field { label: "Turn"; value: window.info.turn }
                        Field { label: "Resume"; value: window.info.resume }
                    }
                }
                Panel {
                    heading: "Canonical State / 仓库"
                    Layout.preferredWidth: 1
                    RowLayout {
                        Layout.fillWidth: true
                        Field { label: "状态版本"; value: "v" + window.info.version }
                        Field { label: "HEAD"; value: window.info.head }
                        Field { label: "工作区"; value: window.info.worktree }
                    }
                    Field { label: "当前阻塞"; value: window.info.blocker }
                    Field { label: "下一步"; value: window.info.nextAction }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                spacing: 12
                Panel {
                    heading: "最近事件"
                    Layout.preferredWidth: 3
                    Caption { visible: window.info.events.length === 0; text: "等待首个任务事件" }
                    Repeater {
                        model: window.info.events
                        delegate: RowLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            Caption { text: modelData.time; Layout.preferredWidth: 42 }
                            Value { text: modelData.session; Layout.preferredWidth: 52; Layout.fillWidth: false }
                            Value { text: modelData.task }
                            Caption { text: modelData.status; color: modelData.status === "失败" ? "#f38d99" : window.accent }
                        }
                    }
                }
                Panel {
                    heading: "可观测 Token Usage"
                    Layout.preferredWidth: 2
                    Caption { text: window.info.usage.message; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    Caption { text: window.info.usage.source; visible: text.length > 0; color: window.accent }
                    GridLayout {
                        columns: 2
                        columnSpacing: 24
                        rowSpacing: 16
                        Layout.fillWidth: true
                        Field { label: "输入 / Input"; value: window.info.usage.input }
                        Field { label: "缓存输入 / Cached Input"; value: window.info.usage.cached }
                        Field { label: "输出 / Output"; value: window.info.usage.output }
                        Field { label: "推理 / Reasoning"; value: window.info.usage.reasoning }
                        Field { label: "总计 / Total"; value: window.info.usage.total; visible: value !== "—" }
                    }
                    Caption { text: window.info.usage.notice; wrapMode: Text.Wrap; Layout.fillWidth: true; lineHeight: 1.3 }
                }
            }
            Caption { text: "独立只读观察者 · 关闭此窗口不会中断 APD Core"; Layout.bottomMargin: 12 }
        }
    }
}
