import importlib

import mlrun


def assert_build():
    for module_name in [
        "torch",
        "transformers",
        "datasets",
        "accelerate",
        "evaluate",
        "deepspeed",
        "mpi4py",
    ]:
        module = importlib.import_module(module_name)
        print(module.__version__)


def create_and_set_project(
    git_source: str,
    name: str = "llm-demo",
    default_image: str = None,
    user_project: bool = True,
    num_replicas: int = 16,
    num_gpus_per_replica: int = 1,
    num_cpus_per_replica: int = 32,
    memory_per_replica: str = "244Gi",
):
    """
    Creating the project for this demo.
    :param git_source:              the git source of the project.
    :param name:                    project name
    :param default_image:           the default image of the project
    :param user_project:            whether to add username to the project name
    :param num_replicas:            number of workers for training
    :param num_gpus_per_replica:    number of GPUs per worker
    :param num_cpus_per_replica:    number of CPUs per worker
    :param memory_per_replica:      amount of memory per worker

    :returns: a fully prepared project for this demo.
    """
    # Get / Create a project from the MLRun DB:
    project = mlrun.get_or_create_project(
        name=name, context="./", user_project=user_project
    )

    # Set or build the default image:
    if project.default_image is None:
        if default_image is None:
            print("Building image for the demo:")
            image_builder = project.set_function(
                "src/project_setup.py",
                name="image-builder",
                handler="assert_build",
                kind="job",
                image="mlrun/ml-models-gpu",
                requirements=[
                    "torch",
                    "transformers[deepspeed]",
                    "datasets",
                    "accelerate",
                    "evaluate",
                    "mpi4py",
                ],
            )
            assert image_builder.deploy()
            default_image = image_builder.spec.image
        project.set_default_image(default_image)

    # Set the project git source:
    project.set_source(git_source, pull_at_runtime=True)

    # Set the data collection function:
    data_collection_fn = project.set_function(
        "src/data_collection.py",
        name="data-collecting",
        kind="job",
    )
    data_collection_fn.apply(mlrun.auto_mount())

    # Set the data preprocessing function:
    project.set_function(
        "src/data_preprocess.py",
        name="data-preparing",
        kind="job",
    )

    # Set the training function (gpu and without gpu for evaluation):
    train_function = project.set_function(
        "src/trainer.py",
        name="mpi-training",
        kind="mpijob",
        image="yonishelach/mlrun-hf-gpu",
    )
    train_function.spec.replicas = num_replicas
    train_function.with_limits(
        gpus=num_gpus_per_replica,
        cpu=num_cpus_per_replica,
        mem=memory_per_replica,
    )
    train_function.save()

    project.set_function(
        "src/trainer.py",
        name="training",
        kind="job",
    )

    project.set_function(
        "src/serving.py",
        name="serving",
        kind="serving",
        image="yonishelach/mlrun-hf-gpu",
    )

    # Set the training workflow:
    project.set_workflow("training_workflow", "src/training_workflow.py")

    # Save and return the project:
    project.save()
    return project
