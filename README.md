# worms-cortex

## Development

When developing isolated in the `worms-cortex` package, you may use a virtual environment. Start by cloning the package into a dev workspace. Navigate to the package and create a virtual environment

```bash
python -m venv .cortex-dev/
```

Activate the environment

```bash
source .cortex-dev/bin/activate
```

Source your ROS2 install

```bash
source /opt/ros/jazzy/setup.bash
```

Navigate back to the workspace directory then build and source the package

```bash
cd ../..
colcon build --symlink-install
source install/setup.bash
```

This will allow VS Code and Ruff to recognize any packages while developing. Now your directory should look similar to the following

```
ws
├── build
│   └── ...
├── install
│   └── ...
├── log
│   └── ...
└── src
    ├── worms-cortex
    └── ...
```