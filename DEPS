deps = {
  "depot_tools": "https://chromium.googlesource.com/chromium/tools/depot_tools.git",
}

hooks = [
  {
    "pattern": ".",
    "action": [
      "python", "infra/appengine/get_appengine.py", "--dest=.",
    ],
  },
]

recursion = 1
