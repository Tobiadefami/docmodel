from dataset import DocModelDataset
from transformers import TrainingArguments
from collator import DataCollatorForWholeWordMask
import fire
import torch
from docmodel.doc_model import RobertaDocModelForMLM, DocModelConfig
from transformers import RobertaForMaskedLM
from transformers import RobertaTokenizerFast, RobertaConfig
from transformers import Trainer, AutoConfig


MAX_BATCH_SIZE_BY_SEQ_LENGTH = {2048: 8, 1024: 16, 512: 32}
STEPS_MULTIPLIER = {2048: 2.7, 1024: 1.6, 512: 1.11}

MODEL_CONFIG = {
    "doc-model-roberta": {
        "model": RobertaDocModelForMLM,
        "config": DocModelConfig,
        "dataset": DocModelDataset,
        "max_length": 2048,
        "gradient_accumulation_steps": 8,
        "tokenizer": RobertaTokenizerFast.from_pretrained,
        "tokenizer_kwargs": {"pretrained_model_name_or_path": "roberta-base"},
        "collator_kwargs": {"include_2d_data": True, "pad_to_multiple_of": 128},
        "pretrained_checkpoint": "roberta-base",
    },
    # "doc-model-xdoc": {
    #     "model": XDocModelForMLM,
    #     "config": DocModelConfig,
    #     "dataset": DocModelDataset,
    #     "max_length": 2048,
    #     "gradient_accumulation_steps": 8,
    #     "tokenizer": RobertaTokenizerFast.from_pretrained,
    #     "tokenizer_kwargs": {"pretrained_model_name_or_path": "microsoft/xdoc-base"},
    #     "collator_kwargs": {"include_2d_data": True, "pad_to_multiple_of": 128},
    #     "pretrained_checkpoint": "microsoft/xdoc-base",
    # },
    "roberta": {
        "model": RobertaForMaskedLM,
        "config": RobertaConfig,
        "dataset": DocModelDataset,
        "batch_size": 16,
        "max_length": 512,
        "gradient_accumulation_steps": 16,
        "collator_kwargs": {"include_2d_data": False},
        "tokenizer": RobertaTokenizerFast.from_pretrained,
        "tokenizer_kwargs": {
            "pretrained_model_name_or_path": "roberta-base",
        },
    },
}


def main(
    experiment_name,
    data_dir=None,
    dataloader_num_workers=0,
    mlm_proba=0.15,
    max_length=None,
    batch_size=None,
    dropout=0.0,
    reading_order="default",
    gradient_checkpointing=True,
    pretrained_checkpoint=None,
    base_model="doc-model-roberta",
    from_scratch=False,
    num_train_epochs=1.0,
    learning_rate=3e-4,
    weight_decay=0.01,
    warmup_ratio=0.1,
    gradient_accumulation_steps=8,
    resume=False,
    # max_steps=10000,
    group_by_length=True,
    **kwargs,
):
    if kwargs:
        raise AssertionError(f"Unexpected arguments: {kwargs}")
    # TODO: start training from random initialization
    # TODO: incorporate other objectives
    model_config = MODEL_CONFIG[base_model]
    pretrained_checkpoint = pretrained_checkpoint or model_config.get(
        "pretrained_checkpoint"
    )
    model_cls = model_config["model"]
    if from_scratch:
        print("Training from random init")
        cfg = model_config["config"]
        model = model_cls(
            config=cfg(
                gradient_checkpointing=gradient_checkpointing,
                attention_probs_dropout_prob=model_config["dropout"],
                hidden_dropout_prob=model_config["dropout"],
                max_position_embeddings=model_config["max_length"],
            )
        )
    else:
        print("Training from pre-trained model")
        config = AutoConfig.from_pretrained(pretrained_checkpoint)
        config.hidden_dropout_prob = dropout
        config.attention_probs_dropout_prob = dropout
        model = model_cls.from_pretrained(pretrained_checkpoint, config=config)

    max_length = max_length or model_config["max_length"]
    if max_length:
        model.resize_position_embeddings(max_length)

    if batch_size is None:
        batch_size = MAX_BATCH_SIZE_BY_SEQ_LENGTH[max_length]

    # max_steps = int(max_steps * STEPS_MULTIPLIER[max_length])
    per_device_batch_size = batch_size or model_config["batch_size"]

    gradient_accumulation_steps = (
        gradient_accumulation_steps or model_config["gradient_accumulation_steps"]
    )

    # print(f"Will train for {max_steps} steps which equates to {max_steps * per_device_batch_size * gradient_accumulation_steps} examples")

    tokenizer = model_config["tokenizer"](
        model_max_length=model_config["max_length"], **model_config["tokenizer_kwargs"]
    )
    args = TrainingArguments(
        output_dir=experiment_name,
        run_name=experiment_name,
        dataloader_num_workers=dataloader_num_workers,
        per_device_train_batch_size=per_device_batch_size,
        do_eval=False,
        evaluation_strategy="no",
        num_train_epochs=num_train_epochs,
        prediction_loss_only=False,
        gradient_accumulation_steps=gradient_accumulation_steps,
        ignore_data_skip=False,
        save_steps=1000,
        save_total_limit=50,
        save_strategy="steps",
        logging_steps=100,
        logging_first_step=False,
        learning_rate=learning_rate,
        warmup_ratio=warmup_ratio,
        weight_decay=weight_decay,
        # max_steps=max_steps,
        report_to="wandb",
        group_by_length=group_by_length,
        fp16=True,
    )
    collator_kwargs = model_config.get("collator_kwargs", {})
    collator = DataCollatorForWholeWordMask(
        tokenizer=tokenizer, mlm_probability=mlm_proba, **collator_kwargs
    )
    dataset_cls = model_config["dataset"]

    train_dataset = dataset_cls(
        directory=data_dir,
        split="train",
        max_length=(max_length or model_config["max_length"]),
        reading_order=reading_order,
    )
    trainer_kwargs = dict(
        model=model,
        args=args,
        train_dataset=train_dataset,
        data_collator=collator,
    )
    trainer = Trainer(**trainer_kwargs)

    if not from_scratch and resume and pretrained_checkpoint is not None:
        trainer.train(pretrained_checkpoint)
    else:
        trainer.train()
    trainer.save_model()


if __name__ == "__main__":
    fire.Fire(main)
