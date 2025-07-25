!pip install transformers
!pip install torch

from transformers import GPT2Tokenizer, GPT2LMHeadModel, GPT2Config, get_linear_schedule_with_warmup
from torch.optim import AdamW

import pandas as pd
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt

import random
import json
import time
import datetime
import os

import torch
torch.manual_seed(64)
from torch.utils.data import Dataset, random_split, DataLoader, RandomSampler, SequentialSampler

!pip show torch

import requests

# Your file's direct download link
url = "https://drive.google.com/uc?id=11jaUwVcO78NT-NurlYPldyaOvNEwo8iV"

# Download the file
response = requests.get(url)
with open("data.json", "wb") as file:
    file.write(response.content)

# Check if the file is saved
print("File downloaded successfully!")

with open("data.json", "r") as f:
  data = json.load(f)
print(len(data))
data[:5]

!nvidia-smi

device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
device

class PoemDataset(Dataset):
  def __init__(self, poems, tokenizer, max_length=768, gpt2_type="gpt2"):
    self.tokenizer = tokenizer
    self.input_ids = []
    self.attn_masks = []

    for poem in poems:

      encodings_dict = tokenizer("<BOS>"+poem["poem"]+"<EOS>",
                                 truncation=True,
                                 max_length=max_length,
                                 padding="max_length",return_tensors="pt")

      self.input_ids.append(encodings_dict["input_ids"].squeeze(0))
      self.attn_masks.append(encodings_dict["attention_mask"].squeeze(0))

  def __len__(self):
    return len(self.input_ids)

  def __getitem__(self, idx):
    return self.input_ids[idx], self.attn_masks[idx]


tokenizer = GPT2Tokenizer.from_pretrained('gpt2',bos_token='<BOS>',eos_token='<EOS>',pad_token='<PAD>')

max_length = 256
batch_size = 16
dataset = PoemDataset(data, tokenizer, max_length=max_length)

train_size = int(0.85*len(dataset))
val_size = len(dataset) - train_size
train_dataset, val_dataset = random_split(dataset, [train_size, val_size])

train_dataloader = DataLoader(train_dataset, sampler=RandomSampler(train_dataset), batch_size=batch_size)

val_dataloader = DataLoader(val_dataset, sampler=SequentialSampler(val_dataset), batch_size=batch_size)

input_ids, attn_mask = dataset[0]
decoded_text = tokenizer.decode(input_ids.tolist(), skip_special_tokens=False)
print("Token IDs:", input_ids)
print("Attention Mask:", attn_mask)
print("Decoded Text:", decoded_text)

device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
device

# Load model configuration
config = GPT2Config.from_pretrained("gpt2")
model = GPT2LMHeadModel.from_pretrained("gpt2", config=config)
model.resize_token_embeddings(len(tokenizer))
model = model.to(device)
epochs = 6
warmup_steps = 1e2
sample_every = 100
optimizer = AdamW(model.parameters(), lr=3e-4, eps=1e-8)


# Toatl training steps is the number of data points times the number of epochs
total_training_steps = len(train_dataloader)*epochs


# Setting a variable learning rate using scheduler
scheduler = get_linear_schedule_with_warmup(optimizer,
                                            num_warmup_steps=warmup_steps,
                                            num_training_steps=total_training_steps)

# Function to format time
def format_time(elapsed):
    return str(datetime.timedelta(seconds=int(round(elapsed))))

# Training loop
for epoch_i in range(epochs):
    print(f"Beginning epoch {epoch_i + 1} of {epochs}")
    t0 = time.time()
    total_train_loss = 0
    model.train()  # Set model to training mode

    # Training step
    for step, batch in enumerate(train_dataloader):
        b_input_ids, b_masks = [x.to(device) for x in batch]  # Move to GPU

        # Zero out gradients
        model.zero_grad()

        # Forward pass
        outputs = model(b_input_ids, labels=b_input_ids, attention_mask=b_masks)
        loss = outputs.loss
        batch_loss = loss.item()
        total_train_loss += batch_loss

        # Backward pass
        loss.backward()

        # Optimize
        optimizer.step()
        scheduler.step()

        # Sampling and logging (reduce sampling frequency)
        if step % 1000 == 0 and step != 0:
            elapsed = format_time(time.time() - t0)
            print(f"Batch {step} of {len(train_dataloader)}. Loss: {batch_loss}. Time: {elapsed}")

            # Sample text generation
            model.eval()
            with torch.no_grad():  # Disable gradient calculation during generation
                sample_output = model.generate(
                    b_input_ids,
                    do_sample=True,
                    max_length=100,
                    top_p=0.95,
                    top_k=50,
                    num_return_sequences=1
                )
                print(tokenizer.decode(sample_output[0], skip_special_tokens=True))
            model.train()

        # Delete variables after each batch to free up memory
        del b_input_ids, b_masks, outputs, loss

    # Average loss per epoch
    avg_train_loss = total_train_loss / len(train_dataloader)
    training_time = format_time(time.time() - t0)
    print(f"Average Training Loss: {avg_train_loss}. Epoch time: {training_time}")

# Saving the model after training
output_dir = "/content/drive/MyDrive/poem_model"
model.save_pretrained(output_dir)
tokenizer.save_pretrained(output_dir)

print(f"Model and tokenizer saved to {output_dir}")

# Validation loop
model.eval()
total_eval_loss = 0
for batch in val_dataloader:
    b_input_ids, b_masks = [x.to(device) for x in batch]

    with torch.no_grad():  # No gradient computation
        outputs = model(b_input_ids, labels=b_input_ids, attention_mask=b_masks)
        loss = outputs.loss

    total_eval_loss += loss.item()

avg_val_loss = total_eval_loss / len(val_dataloader)
print(f"Validation Loss: {avg_val_loss}")

del model
del tokenizer
torch.cuda.empty_cache()  # Clear cache

from transformers import GPT2LMHeadModel, GPT2Tokenizer

# Reload the model and tokenizer
model = GPT2LMHeadModel.from_pretrained(output_dir)
tokenizer = GPT2Tokenizer.from_pretrained(output_dir)

# Move the model to the appropriate device (GPU/CPU)
model = model.to(device)

# Set the model to evaluation mode
model.eval()

def generate_poem(prompt, max_length=200, temperature=1.0, top_p=0.95, top_k=50):
    # Tokenize the prompt
    inputs = tokenizer.encode(prompt, return_tensors="pt").to(device)

    # Generate the poem
    outputs = model.generate(
        inputs,
        do_sample=True,
        max_length=max_length,
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        num_return_sequences=1
    )

    # Decode and return the generated text
    generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
    return generated_text

prompt=input()
final_prompt = f"<BOS> {prompt}"
generated_poem = generate_poem(final_prompt)
print(generated_poem)
