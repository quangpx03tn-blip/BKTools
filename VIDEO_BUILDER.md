# Tool 4: Xưởng dựng video

`/camera_movement.html` now opens a production board. The previous Camera & Shot Designer remains at `/camera-designer.html`.

## Workflow

1. Import scenes from Tool 2, a saved Camera Designer shot list, or SRT.
2. Review voiceover, timing, shot size, movement, transition, image prompt, and video prompt per scene. Optional camera analysis uses the existing `/api/analyze-camera` route and the user's API key.
3. Attach images or clips per scene, or select many files named `scene_001.png`, `scene_002.mp4`, etc.
4. Attach voice, SRT, and music, then export a ZIP with media, `timeline.csv`, `manifest.json`, `prompts.txt`, and video prompts grouped by 4, 6, 8, or more seconds.

Text state saves in browser localStorage per project. Media files must be selected again after a reload. The export ZIP is an editable asset package; it is not an automatically generated CapCut project.

The source copy at `E:\Tools\BK Tools` is unchanged until the revised files are copied there.
