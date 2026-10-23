import discord
from discord.ext import commands
from discord import app_commands
import chat_exporter
import io
import datetime

# --- BOT CONFIGURATION ---
TOKEN = "YOUR_DISCORD_BOT_TOKEN"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- STEP 2: PAYMENT METHOD MODAL ---
class PaymentModal(discord.ui.Modal):
    def __init__(self, item_name: str, item_details: str):
        super().__init__(title="Step 2: Payment Details")
        self.item_name = item_name
        self.item_details = item_details

        self.payment_method = discord.ui.TextInput(
            label="Which payment method are you using?",
            placeholder="e.g., PayPal, UPI, Crypto (BTC/LTC), Credit Card...",
            max_length=100,
            required=True
        )
        self.additional_notes = discord.ui.TextInput(
            label="Any additional notes or promo codes?",
            style=discord.TextStyle.paragraph,
            placeholder="Optional extra details...",
            max_length=500,
            required=False
        )

        self.add_item(self.payment_method)
        self.add_item(self.additional_notes)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        # Get or create 'Buy Tickets' Category
        ticket_category = discord.utils.get(guild.categories, name="Buy Tickets")
        if not ticket_category:
            ticket_category = await guild.create_category("Buy Tickets")

        # Channel Permissions: Only the buyer and admins can see it
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }

        channel_name = f"buy-{interaction.user.name.lower()}"
        ticket_channel = await guild.create_text_channel(
            name=channel_name,
            category=ticket_category,
            overwrites=overwrites,
            topic=f"Order by {interaction.user.name} | User ID: {interaction.user.id}"
        )

        # Build Purchase Ticket Overview Embed
        embed = discord.Embed(
            title="🛒 New Purchase Order",
            description=f"Welcome {interaction.user.mention}! A staff member will process your order shortly.",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.add_field(name="📦 Item / Product Requested", value=self.item_name.value, inline=False)
        embed.add_field(name="📝 Quantity / Details", value=self.item_details.value or "None specified", inline=False)
        embed.add_field(name="💳 Payment Method", value=self.payment_method.value, inline=False)
        
        if self.additional_notes.value:
            embed.add_field(name="📌 Additional Notes", value=self.additional_notes.value, inline=False)

        embed.set_footer(text=f"Buyer ID: {interaction.user.id}")

        await ticket_channel.send(embed=embed, view=TicketControlView())
        await interaction.followup.send(f"✅ Your purchase ticket is ready: {ticket_channel.mention}", ephemeral=True)


# --- STEP 1: ITEM TO BUY MODAL ---
class BuyItemModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Step 1: What are you buying?")

        self.item_name = discord.ui.TextInput(
            label="What do you need to buy?",
            placeholder="e.g., VIP Subscription, Discord Bot, Product Name...",
            max_length=100,
            required=True
        )
        self.item_details = discord.ui.TextInput(
            label="Quantity / Specific Options",
            style=discord.TextStyle.paragraph,
            placeholder="e.g., 2 Months duration, Red color scheme, etc.",
            max_length=500,
            required=True
        )

        self.add_item(self.item_name)
        self.add_item(self.item_details)

    async def on_submit(self, interaction: discord.Interaction):
        # Trigger Modal 2 (Payment Details) right after submitting Modal 1
        await interaction.response.send_modal(
            PaymentModal(
                item_name=self.item_name.value,
                item_details=self.item_details.value
            )
        )


# --- BUTTON TO LAUNCH ORDER FLOW ---
class TicketLaunchView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Buy Something", style=discord.ButtonStyle.success, emoji="🛒", custom_id="open_buy_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BuyItemModal())


# --- TICKET CONTROL PANEL (Inside the channel) ---
class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Order", style=discord.ButtonStyle.red, emoji="🔒", custom_id="close_buy_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("⚙️ Generating HTML transcript and closing order...", ephemeral=True)

        channel = interaction.channel

        # Generate HTML Transcript
        transcript_html = await chat_exporter.export(
            channel,
            limit=None,
            tz_info="UTC",
            military_time=False,
            bot=bot
        )

        if transcript_html is None:
            await interaction.followup.send("❌ Failed to generate transcript.", ephemeral=True)
            return

        transcript_file = discord.File(
            io.BytesIO(transcript_html.encode('utf-8')),
            filename=f"transcript-{channel.name}.html"
        )

        # Parse Buyer User ID from channel topic
        user_id = None
        if channel.topic and "User ID: " in channel.topic:
            try:
                user_id = int(channel.topic.split("User ID: ")[-1])
            except ValueError:
                pass

        embed_dm = discord.Embed(
            title="Order Ticket Closed",
            description=f"Your purchase order ticket **#{channel.name}** in `{interaction.guild.name}` has been closed.\nAn HTML copy of your order transcript is attached below.",
            color=discord.Color.dark_red(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )

        # Send HTML transcript via DM
        if user_id:
            user = interaction.guild.get_member(user_id) or await bot.fetch_user(user_id)
            if user:
                try:
                    await user.send(embed=embed_dm, file=transcript_file)
                except discord.Forbidden:
                    pass

        await channel.send("⚠️ This channel will be deleted in 5 seconds...")
        await discord.utils.sleep_until(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=5))
        await channel.delete()

    @discord.ui.button(label="Claim Order", style=discord.ButtonStyle.secondary, emoji="🙋‍♂️", custom_id="claim_buy_ticket")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ Only staff members can claim order tickets.", ephemeral=True)
            return

        embed = discord.Embed(
            description=f"🖐️ Order claimed by {interaction.user.mention}. They will assist you with payment instructions.",
            color=discord.Color.blue()
        )
        button.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message(embed=embed)


# --- BOT SETUP ---
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"Error syncing slash commands: {e}")


@bot.tree.command(name="setup_shop", description="Creates the buy ticket portal.")
@app_commands.checks.has_permissions(administrator=True)
async def setup_shop(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🛒 Purchase & Store Tickets",
        description="Click the button below to start your purchase.\n\n"
                    "**How it works:**\n"
                    "1️⃣ Tell us what you want to buy.\n"
                    "2️⃣ Tell us your preferred payment method.\n"
                    "3️⃣ A private channel will open with staff to finalize payment.",
        color=discord.Color.green()
    )
    embed.set_footer(text="Automated Checkout Assistant")

    await interaction.channel.send(embed=embed, view=TicketLaunchView())
    await interaction.response.send_message("Shop panel sent successfully!", ephemeral=True)

bot.run(TOKEN)
