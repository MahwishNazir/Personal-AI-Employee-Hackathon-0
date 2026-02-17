from skills.task_analyzer import run as analyze_tasks
from agents.task_agent import run as agent_run
from watcher import watch


def main():
    print("Hello from ai-employee-vault!")
    # Start the watcher loop; each cycle runs: scan inbox -> analyze pending -> complete processing
    watch(on_cycle=[analyze_tasks, agent_run])


if __name__ == "__main__":
    main()
