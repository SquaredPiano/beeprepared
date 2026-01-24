import re
import os
import logging
from google import genai
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

class TextCleaner:
    def __init__(self):
        self._setup_gemini()

    def _setup_gemini(self):
        """Initialize Gemini client using google-genai SDK."""
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                self.client = genai.Client(api_key=api_key)
                self.model_name = 'gemini-2.0-flash-exp'
            except Exception as e:
                logger.error(f"Failed to initialize Gemini: {e}")
                self.client = None
        else:
            logger.warning("GEMINI_API_KEY not found. LLM cleaning will be skipped.")
            self.client = None

    def clean_regex(self, text: str) -> str:
        """
        Performs fast, rule-based cleaning using Regex.
        - Removes timestamps (e.g. 0:00, 1:05:20).
        - Removes speaker labels (e.g. BRANDON:, STUDENT:).
        - Removes parentheticals/stage directions (e.g. (laughing)).
        - Remove filler words + normalize whitespace.
        """
        if not text:
            return ""

        # 1. Remove Timestamps (e.g. 0:00, 12:30, 1:05:00) on their own line or inline
        text = re.sub(r'\b\d{1,2}:\d{2}(:\d{2})?\b', '', text)

        # 2. Remove Speaker Labels (e.g. BRANDON:, STUDENT:)
        # Looking for UPPERCASE words followed by colon at start of line or sentence
        text = re.sub(r'\b[A-Z]+:\s*', '', text)

        # 3. Remove Parentheticals/Stage Directions (e.g. (laughing), [inaudible])
        text = re.sub(r'\([^\)]+\)', '', text)
        text = re.sub(r'\[[^\]]+\]', '', text)

        # 4. Normalize whitespace (tabs/newlines -> space, multiple spaces -> single)
        text = re.sub(r'\s+', ' ', text).strip()

        # 5. Remove filler words (case-insensitive, standalone)
        fillers = [r'\bum\b', r'\buh\b', r'\bah\b', r'\ber\b', r'\bhmm\b']
        for filler in fillers:
            text = re.sub(filler, '', text, flags=re.IGNORECASE)

        # 6. Handle "like" specifically
        text = re.sub(r'\blike\s+', ' ', text, flags=re.IGNORECASE)

        # 7. Fix punctuation
        text = re.sub(r'\s+([.,!?;:])', r'\1', text)
        text = re.sub(r'\.+', '.', text)

        return text.strip()

    def clean_with_gemini(self, text: str) -> str:
        """
        Uses Gemini to fix transcription errors and standardize terminology.
        """
        if not self.client:
            logger.warning("Gemini client not initialized. Skipping LLM cleaning.")
            return text

        logger.info("Sending text to Gemini for refinement...")
        
        prompt = f"""
        You are an expert editor processing raw audio transcripts.
        Your goal is to IMPROVE clarity and correctness WITHOUT summarizing or changing the meaning.

        Instructions:
        1. Fix transcription errors (e.g. "SQL" vs "sequel").
        2. Standardize technical terminology.
        3. Remove remaining stuttering or filler words.
        4. Fix grammar/sentence structure for readability.
        5. DO NOT summarize. Output length should be roughly same as input.
        6. Return ONLY the cleaned text.

        Raw Text:
        {text}
        """

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            if response.text:
                return response.text.strip()
            return text
        except Exception as e:
            logger.error(f"Gemini cleaning failed: {e}")
            return text

    def clean_text(self, text: str, use_llm: bool = True) -> str:
        """
        Main orchestration method for text cleaning.
        """
        logger.info("Starting text cleaning...")
        
        # 1. Regex Pass (Fast)
        cleaned_text = self.clean_regex(text)
        
        # 2. LLM Pass (Smart)
        if use_llm and self.client:
            cleaned_text = self.clean_with_gemini(cleaned_text)
            
        logger.info("Text cleaning completed.")
        return cleaned_text

if __name__ == "__main__":
    # Test Block
    cleaner = TextCleaner()
    
    raw_input = """
In this video
Intro
0:00
BRANDON: Hey! Brandon Sanderson here. Welcome to  the 2025 lecture series. These are lectures that  
0:05
I give at my local university, Brigham Young  University, about science fiction and fantasy   writing. Every week I'm going to have a new one  for you. This week we're doing mostly introductory  
0:15
material. I'm going to talk about my philosophy  in teaching this class. I'm going to talk about  
0:20
the difference between a discovery writer and  an outline writer. I'm going to talk about a   lot of interesting sort of philosophy of how to  approach being a writer with the eye toward being  
0:30
a professional, as long as we're in this class.  It's not how you have to do it, but it's what  
0:36
I'm going to assume for the hours that you're here  with me. So join me here, and then I will see you  
0:43
back every week, hopefully, for another lecture. Hey! Welcome to class!  CLASS: (cheering and applause) BRANDON: Oh, I surprised you. 
0:56
CLASS: (cheering and applause) BRANDON: This is How to Write Science Fiction and   Fantasy. If you're not here for science fiction  and fantasy, well, you can stay. We'll convert  
1:06
you. We love having you here. So, what this class  is, is Brandon lectures at you for approximately  
1:17
an hour and a half, I believe. And we started  this up with it being kind of a normal 218 class,  
1:26
How to Write Science Fiction and Fantasy.  The class burgeoned. It grew as my notoriety  
1:34
grew to eventually the point that people were  packing in, and we had to move to a lecture hall.  Hey, how you doing? STUDENT: How are you doing? 
1:42
BRANDON: I'm doing all right. So, these  days it really is, and this is how I run it,  
1:47
a lecture series. Now, after this, there  is the second class. I should have my 15,  
1:54
16 this year, people here who are in that  class. That's the by application only.  
2:00
We'll figure out what we're doing with you  afterward. And the rest of you, you're welcome   to apply for that class. That one's by application  only, and we do it every year after this class. 
2:11
So what are we going to do in this class? Well,  I am going to come every week, and I am going to   turn on a firehose of information. Right? And  I'm going to blast you with this firehose of  
2:23
information, and you're going to try to drink  some of it. And that which you can't drink,   you can hopefully come back and get on the videos  that we are posting this year on YouTube. So  
2:34
you're being recorded. Not much of you. CLASS: (laughing)  BRANDON: Only your laughter and maybe the  backs of some of your heads. That's why we're  
2:43
in this new, fancier room. ADAM: We have a camera   that's going to be capturing their faces. BRANDON: Oh. Your faces are on the camera too. 
2:56
CLASS: (cheering) BRANDON: You should have had to sign a thing.  CLASS: (laughing) BRANDON: That says we're going   to make you internet famous, Nate. CLASS: (laughing) 
3:05
BRANDON: By the way, who here took the  class last year? Those who were here   last year, Nate finished a book! CLASS: (cheering and applause) 
3:21
BRANDON: Nate finished a second book! CLASS: (cheering and applause) 
3:29
BRANDON: He's actually finished three, which  means he's one off from running a Kickstarter. 
3:38
CLASS: (cheering and applause) BRANDON: Joking. Joking. Joking. So I might  
3:44
make some of you--. So anyway, last year he had  expressed that he had trouble, as many authors do,  
3:51
getting really into a project, starting to  write, and then losing momentum and revising  
3:58
the same chapter over and over again and never  finishing anything. Am I paraphrasing it right,   Nate? And so I started checking up on him every  week and embarrassing him in front of class, and  
4:07
he was a very good sport. So I'm happy to see you  back, and congratulations. Well done. You're back,  
4:14
too, aren't you? STUDENT: Yeah.  BRANDON: Yeah. Good to see you. Some of you  I recognize. Some of you--do I recognize you? 
4:21
STUDENT: Yes. BRANDON: Yeah. People take the class   so often. You guys intimidate--. Hey! They're  all up here. Hey, I recognize you. That's Skar. 
4:29
CLASS: (laughing) STUDENT: He's   annoying. You probably don't remember. BRANDON: I totally know your name. 
4:36
EL: Elle. BRANDON: That's right,   Elle. I told you I was going to remember  your name. I promised I would at some point. 
4:42
EL: You even put me in a whole book. BRANDON: Yeah. Welcome, Elle. You   told me that last time too. I  spelled it differently though. 
4:48
EL: E-L. BRANDON: E-L, not just the letter. OK. Well,   welcome, El. Good to see you again. So, we will  have lots of people running around, doing video  
4:58
recordings. Ignore them. Pretend they're not  here. So what do we got? Well, because we're  
5:06
getting recorded this year, I'm going to try to do  better to write on the board what we're going to   talk about each week, and then actually keep to  it. We'll see how much I deviate from that with  
5:16
various tangents, which I do love and enjoy.  But we are going to approach this class from  
5:24
a sort of--we'll talk about this later--a nuts  and bolts approach. This shouldn't, hopefully,  
5:30
ruin your artistic expression. In fact, it  should help elevate it. We'll talk about that. 
5:35
We are going to spend two weeks each on plot,  setting, character, and the business of writing.  
5:43
All right? Those are kind of our core ideas that  we'll cover. I'm usually gone at least one week,  
5:51
and I bring in guest lecturers. In the past,  guest lecturers have been people to focus on  
5:57
short story writing, or on indie publishing.  And I'll try to get somebody like that who  
6:03
can cover a realm of publishing that--from a  place of more expertise. Right? Because on one  
6:12
metric I'm the most successful indie published  author ever. But that metric was trading on my  
6:18
already established traditionally published  name. So I usually--we'll see what happens  
The Philosophy of the Class
6:24
that week. So that'll cover nine of our weeks. Several of our other weeks will be Q&A sessions.  
6:31
Usually what I like to do is I like to have two  weeks on, say, plot, and then a Q&A on plot;  
6:39
two weeks on setting, then a Q&A on setting; two  weeks on character, Q&A; two weeks on business,  
6:44
Q&A. Right? And that should basically cover  the class. In there somewhere I do tend to  
6:52
try to squeeze in mini lectures on revision,  and a mini lecture on prose. So we'll see  
6:59
what we can do with those sorts of things. But let's talk about the beginning idea,  
7:06
my philosophy for this class. What is my  philosophy for teaching and for teaching writing  
7:14
in particular? Because writing is kind of hard to  teach. Not to make my job sound more cool, because  
7:22
it's kind of hard to teach because you will learn  more than I can teach you in this class. Hey,  
7:30
how you doing? By writing your first book, than  myself or any person can possibly teach you.  
7:40
Right? Writing as an art requires work and effort.  Everything requires work and effort. But the thing  
7:49
about a lot of artistic pursuits like this is,  you need to start exploring with your style. Hey,  
7:57
you're back too. Good to see you. Exploring with  your style. Seeing how it goes. Revising. Trying  
8:07
different things. And as you explore writing, you  will get better and better, and you will know how  
8:14
to use the tools that people like myself give  you. You will also know which tools to ignore. 
8:23
Because one of the key philosophies I  have is, writing advice is only as good  
8:30
as its ability to help you individually. You will  get bad advice for you. You will get bad advice  
8:38
for you from me in this class. OK? I try hard not  to give you too much of that. But the thing is,  
8:46
writing is so individual that what works for some  writers doesn't work for others. For example,  
8:53
the one I often use because it hit me when I  was young, and I was working. I was reading  
8:59
a book by Orson Scott Card where he talked about  writing, and in it he talked about how important  
9:05
an outline was to his writing, and without it  his writing would become a disaster. I then  
9:10
later read an essay by Stephen King. It may have  even been in On Writing, his famous writing book,  
9:16
where he talks about how an outline is the  great destroyer of stories. And if you have  
9:23
an outline for your story, it's going to ruin  your story. And these are polar opposites. Right?  
9:30
And can you do both? Well, the answer is yes. Most everyone in this room is going to be some  
9:36
mix of what George R. R. Martin calls a gardener  versus an architect. He's very good with words,  
9:42
and that's one of his descriptions that I love.  He says some writers are an architect. They build  
9:47
themselves a structure for their story, like  a house. And then they hang a story upon it.  
9:54
Other writers, he says, are like a gardener. They  go out in the garden, and they nurture something   as it starts to grow. And then they see what it  becomes. You might have heard the term pantsing  
10:05
for writing. People use that. The truth is  that most writers are somewhere in between   those two extremes. But you won't know where you  are, and indeed what a given project requires,  
10:17
until you try both of them and make your own  Frankenstein monster of a style and a process  
10:25
out of the things that everyone tells  you, and what you discover on your own,   and that monster will grow and change through  your career, and you will do different things. 
10:34
So why am I sometimes going to give you bad  advice? Well, it's because it works for 90%  
10:41
of authors but you're the 10%. Or it might be  the advice that is good for you 20 years from  
10:47
now when you've changed as an author and you're  like, "Hey, I remember that thing. Let's try   that." But right now, it could be destructive. Our philosophy, my philosophy, is to treat you  
10:59
like a chef and not a cook. Those who have been in  this class before know I love this metaphor. What  
11:08
does this metaphor mean? Well, in my definitions,  a chef is someone like me when it comes to baking,  
11:15
who can follow a recipe. And if I follow the  recipe, usually I'll get what I'm trying to make,  
11:22
and it usually tastes something like what I'm  trying to make. The problem is, if something  
11:28
goes wrong, I have no idea why it went wrong  and what I could have done to change it. I  
11:36
have no idea what temperature does to baking,  only that on this page it says bake it at 325,  
11:43
and if I do that it usually turns out. I don't  know the difference between baking soda and  
11:48
baking powder. Except on the page it says use  one and not the other, and if you mix them up  
11:53
it's bad. Right? That is what I will term a cook. What is a chef? A chef is a person who can tell  
12:01
you, "Well, when you add this ingredient, it  does this." A chef is a person who can taste  
12:07
something and be like, "Oh, this is what went  wrong. Let's try it this way next time and see   if it improves it." A chef is someone who  can take the various styles of baking that  
Being a Pro vs Non-Pro
12:17
different people use and apply them to their own  process and create new things, not from a recipe,  
12:23
but that use the knowledge of previous recipes  to create masterful new works. I want you to be  
12:29
a chef when it comes to writing. I want you to  learn all the tools and processes. I want you  
12:34
to learn all the tools and processes. I want you  to try them. I want you to work with them. And   as you do, learn how to create the effect you  want to have with your stories as you write and  
12:44
finish them, rather than the effect other people  say you should have. Your goals can be your own. 
12:52
And I'm slightly out of order here because let's  talk about being a pro versus being a non-pro  
12:57
writer. It is OK. In fact, it is wonderful, to  be a nonprofessional writer. You can be in this  
13:06
class for any reason. You could have wandered in  accidentally, seen that there were people here,  
13:11
and taken a seat, you weirdo. CLASS: (laughing)  BRANDON: Right? You're welcome. You're welcome  here. You can be here because you're like, "That  
13:23
Sanderson guy, maybe if I take his class I'll  get a book signed." You shouldn't be doing that,  
13:28
but I'll make you learn anyway, and so it's good  for you. You might be here because you're like,  
13:34
"Well, I need to have a certain number  of writing credits and, you know,   this is the class that's in the evening that I  can take." You might be here because you want to  
13:42
be a better GM. You might be here because you  just love the process. Or you might be here,  
13:49
as the majority of you probably are,  because you're like, "Maybe I could   become a professional science fiction/fantasy  writer." Those are all valid reasons to be  
13:59
here. I would guess the most--the balance,  the most common is those who want to be a pro,  
14:05
and those who would like to learn to write  a good book now and then as a hobby. Those   are my most common students. Wonderful. I think  writing is good for you. And one of the things  
14:18
you're going to have to confront, when you're  writing stories and you tell people about it,  
14:23
they're going to ask you a question. Have  you been asked this question? What is it? 
14:29
CLASS: Are you published? BRANDON: Are you published? What are you going   to do with this? How soon till you can take me out  to dinner with the money you make from your books? 
14:38
CLASS: (laughing) BRANDON: Right?  We live in a society that likes to approach things  from a utilitarian eye. There are advantages to  
14:47
that. Right? There are advantages to  my mother, when I was 16, discovering  
14:54
that I wanted to be a writer, and saying,  "That's nice, dear. You should be a doctor." 
15:01
CLASS: (laughing) BRANDON: And I'm like, "But doc--."   She's like, "Doctors have a lot of free time. You  know how doctors are always golfing? Right? Well,  
15:08
you could be a doctor who writes fantasy novels  instead of golfing and also feed your family." 
15:17
CLASS: (laughing) BRANDON: She really wanted a doctor,   and she got none out of her four children. CLASS: (laughing)  BRANDON: Yeah. No doctors. No doctors.  She got me. She got my brother who's in  
15:26
computer programming. That's close to being a  doctor. He got the closest. She got a teacher.  
15:33
And she got an artist/fashion designer/charity  organizer. That's Jane, who runs Lightweaver for  
15:43
me. And so she got no doctors. She got none  married to doctors. But she loves us anyway. 
15:51
CLASS: (laughing) BRANDON: There is an advantage   to people saying that because you do need to  ask those questions. Right? But our society  
16:02
treats art too utilitarianly. It doesn't look at  the primary purpose of art, which is making the  
16:11
artist's life more enriched, is sincerely what  I believe the primary purpose is. It is to make  
16:18
your life better by creating something. When  you go play basketball, unless you happen to  
16:27
have a Wemby-esque height, people are probably not  going to ask you after your game in, you know, the  
16:33
church gym, and you're like, "Oh, I can--." You  know. And you maybe look more like me. They're not  
16:40
going to say, "So, when are you going to the NBA?"  They just--they won't. But they will ask you when  
16:47
you're going to sell your writing. They're going  to ask you if you're published. And that's OK. 
16:54
But I want you to understand that's not why  you have to write. In fact, it's probably not  
17:00
why you should write. Writing is good for you.  Expressing yourself is good for you. Creating  
17:06
art is good for you. That all said, we are going  to pretend when you walk through those doors,  
17:15
that every one of you is in the category that  I mentioned that wants to be making a full-time  
17:21
living as a science fiction and fantasy novelist  within the next 10 years. The reason for that is,  
Making a Living as a Novelist
17:29
all the other advice that I would give you to  be a better GM, or to be better at writing in   your journal, or to be fulfilled as writing  a book every 20 years, or every five years,  
17:41
for your sisters like Jane Austen did, all of that  advice is circumscribed in the advice I would give  
17:49
to the aspiring professional. And I want to give  you all the possible tools that I can so that  
17:58
you can become that professional if someday  you decide that you want to. But let's take  
18:06
a moment to look at it realistically. Probably  the only time in this class that we will do that. 
18:14
CLASS: (laughing) BRANDON: Making a living as a professional   novelist, or as a professional musician working  on kind of the highest record label touring level,  
18:26
or as a fine artist not working in commercial  illustration, these jobs are hard. Not that  
18:36
they're any harder to do than other types of jobs,  but they are harder to make a living at than other  
18:42
kinds of jobs. As a writer, there are lots of  options open to you, and I'm sure the university  
18:48
will tell you what they are. Skar wrote for  a hearing aid company for how many years? 
18:55
SKAR: Ten. BRANDON:   Ten years wrote copy in the hearing aid company  for their hearing aid books about, you know-- 
19:02
SKAR: How to operate the hearing aids. BRANDON: How to operate the hearing aids.  CLASS: (laughing) BRANDON: You can tell the enthusiasm in his voice. 
19:08
CLASS: (laughing) BRANDON: By the way,   if you don't know Skar, Skar works at Dragonsteel.  He is one of my executive assistants. Becky is  
19:15
the other one. She's back there. They are  here to facilitate making things happen,  
19:21
and to get me in the place where I'm supposed  to be at the time I'm supposed to be there. 
19:27
Dan went on--Dan, friend of mine--he wrote for  the newsletter for a scrapbooking company. There  
19:33
are lots of those kinds of jobs. Writing fiction  and making a living at it is hard. Now, it's not  
19:43
as hard as they told me when I took this--was  taking classes like this when I was young. It's  
19:49
not as hard as my mom thought. She would have told  you it's one in a million. If you had asked other   people they'd be like, you know, one in 10,000,  whatever. I took this class in 1999. (sighs) 
20:05
CLASS: (laughing) BRANDON: Yeah, I know. I used to think of myself   as the young guy. Now this is the young people  over here. When I took this class in 1999 from  
20:14
Dave Wolverton who has since passed on, in that  class was myself, Dan Wells who went on to become  
20:23
a professional novelist, and Stacey who became  a professional editor, and Peter who became a  
20:30
professional editor, as well as two people I would  list as semi-pros. But there's four pros in that  
20:37
class of around 30 people. OK? That's pretty good. My odds have generally been, in my 15-person  
20:45
class, one to a half of a person every year  going pro, depending on your definition of  
20:52
going pro. More than one will get a book published  professionally. But one to a half of one a year,  
20:59
so one every two years, will go on to make a  significant portion of their living from writing,  
21:04
is about the odds that we have had. Janci took my  class, and she went full pro. Brian McClellan took  
21:11
my class. He went full pro. There's a bunch of  them. I can't list them all right now. That's not  
21:17
because I'm such a great teacher. I hope that I'm  good. But it's more along the lines of if you are  
21:23
seriously dedicated to this and willing to invest  10 years in it, you've probably got more like a  
21:29
one in 20 shot of making a significant portion of  your income from writing than one in a million. 
21:38
Now that does not count the fact that a lot  of people are going to give up before then,  
21:44
so it's probably better than one in 20. But,  you know, that's better odds than people  
21:53
pretend. Right? You would not have thought  that. Let's acknowledge that of the people  
22:01
that went pro that are my friends or in that  class, only one of them is regularly hitting  
22:07
the New York Times best-seller list. Right?  But you can make a living without doing that  
22:13
or significantly contribute to your income. That said, if you went and took a class in the  
22:21
Computer Science Department and the professor got  up and said, "I think maybe one in 20 of you can  
22:28
actually make some of your living at this, maybe  one in 50 fully on professional are going to be  
22:36
able to," you would leave. CLASS: (laughing)  BRANDON: Right? You would be like,  "I am going to chemical engineering." 
22:45
STUDENTS: (cheering) BRANDON: Oh, the chemical engineers. They   have a 90-something-percent placement rate.  Right? Do you guys know what it is? It used  
22:52
to be the highest at BYU, which is why I used  that one as a joke. Are you chemical engineers?  STUDENT: Yes. BRANDON: My freshman roommate  
22:59
was a chemical engineer. If you've ever read  the Mistborn books, Captain Conrad is based  
23:04
off of Tom Conrad, a good friend of mine still.  He went on to work for Intel. He is a glorified  
23:10
sewage treatment plant engineer. Right? Because  he cleans their water for Intel. That's his job.  
23:16
He loves cleaning water. He gets the dirty water  and he figures out how to separate all the stuff   out that you can sell for money, and then make  the rest of the stuff nontoxic so you can then  
23:25
dispose it, or purify it so that it can be used  elsewhere. That's Tom's job. He's very good at it. 
23:32
But it's good to bring up chemical engineering  because when I was in school, in this class,  
23:38
taking this class, Tom was getting put through  the wringer. You people, I'm so sorry. He would  
23:44
come back and be like, "Ah, I got a 61 on  my test." And I'd be like, "Oh!" You know. 
23:52
CLASS: (laughing) BRANDON: "I'm in the arts." Right? Like,   we don't look at those numbers. And he's like,  "Oh, no. I was second highest in the class." 
24:02
CLASS: (laughing) BRANDON: Yeah, we talked about sonnets   and shared our feelings, and all got A's. CLASS: (laughing) 
24:14
BRANDON: But if you want to be going pro  in the next 10 years, you're going to have  
24:20
to pretend you're in the Chemical Engineering  Department, but for writing. So my philosophy,  
24:26
again, is to encourage an aggressive,  for whatever your definition of that is,  
24:34
writing schedule during your early years in  order for you to learn your process. Your job  
24:45
as a writer right now, if you have not finished  at least three novels--I'm just pulling that out  
24:51
of the air. It could be--but let's just go with  that. If you haven't finished at least three,   maybe if you haven't finished five. I sold  my sixth. Dan sold his sixth. You sold your-- 
25:01
RACHEL: Seventh. BRANDON: Seventh. Right?   If you haven't, you know, if you haven't  done that many, that's not where you are,  
25:10
your job is not to sell books. Even if you want  to be a professional. Your job is to write enough  
25:15
books to learn your process and what works for  you. And this is where the bad advice comes in.  
25:22
Once in a while there's a stupid Pat Rothfuss  who writes a brilliant book their first time. 
25:28
CLASS: (laughing) BRANDON: And then revises it a ton, because   he did, sweat and tears. You know Pat. He revised  it maybe to insane levels. But once in a while  
25:41
there's a stupid Pat Rothfuss who's brilliant at  the start and just writes a really great book.  
25:47
Harry Potter was a first book. Twilight was a  first book. Name of the Wind was a first book.  
25:52
Elantris was my sixth. Mistborn was my 14th. I  find a lot more of those than I find of your first  
26:01
book. And most of the people I know whose first  book got published kind of wish that they had then  
26:07
written several more books before they published  it so that when they published that first book   they already knew their style, so that when the  weight of deadlines hit them, they already were  
26:21
practiced at consistently writing. And that  for--if you are so lucky as to get published,  
26:28
you're suddenly going to have deadlines. You're  suddenly going to have to write while the entire  
26:33
world is critiquing what you've done. You're  somehow going to have to keep writing as you  
26:41
stress about whether or not your books are selling  any copies, and worrying they're not selling   enough copies, and trying to deal with publicity,  and trying to deal with all of the headaches and  
26:51
heartaches that come from being a professional.  And if you have not spent years practicing so  
26:59
that writing and the habits of it are secondhand,  that part is so much harder, so very much harder. 
27:10
So, if you have not finished several novels, let's  say--. I heard early on that your first five books  
27:19
are generally crap, and it was good advice for  me because I said, "Oh, I don't have to stress   about this for five books." And I wrote five  books, and they were mediocre. And I said, "I  
27:27
love epic fantasy. I've spent this time learning  this." And then I sat down, and I wrote Elantris,   and it sold. Still took a couple of years, but  it sold. Who knows? That was definitely the right  
27:38
advice for me. Is it right advice for you? I  don't know. But I'm telling you right now, you   should probably approach your writing as you might  approach playing the piano, and your first books  
27:49
are learning your scales. This can be really hard  for some people. It can be really hard generally  
27:57
for most people, knowing that this beautiful thing  that you're working on--. You have this baby that  
28:04
you've cherished. And you might have cherished  this baby since you were a teenager, meaning "I'm  
28:12
going to write this book someday." And you might  have written in your books in school, as I did,  
28:18
sketches of your characters and ideas for plot  lines for that book that you're going to write.   And you may have this book that built over many  years. And you might run into the situation upon  
28:28
writing it that suddenly your baby is ugly. CLASS: (laughing) 
28:34
BRANDON: It's here and it's ugly and what do you  do? Oh no! And it's even worse than the baby being   ugly. You know the baby is actually--well, the  baby was perfect in your mind, this book. It  
28:43
was gorgeous and beautiful. And then you made  it ugly through your fat fingers being unable  
28:49
to accomplish what you want to accomplish. Very  deadly to new writers because they get stopped,  
28:56
because their skill isn't up to their aspirations  yet. You need to push through that and keep  
29:01
writing. You need to learn early on that the  product of your writing time is yourself. You  
29:09
are the artwork. The time you spend writing will  change you. It will make you better at expressing  
29:18
your ideas. It will make you--you'll have a  wonderful time. It's just wonderful writing.   But you will also grow as a person. You  will become more empathetic. All of these  
29:27
things will happen to you. The product of your  writing time is you. You are the piece of art.  Now, as you get better and better at that,  that time spent making yourself better does  
29:38
start producing things that hopefully you can  sell. My philosophy on artistic expression is,  
29:46
while you are writing the book, the artist should  be in control. You should be making the decisions  
29:54
that the artist thinks are genuinely the best  decisions for that story and those characters.  
30:00
The moment you finish that book, there should be a  second person inside of you who takes the artist,  
30:07
shoves them in a closet, locks the door,  takes the manuscript, and runs away cackling. 
Philosophy on Artistic Expression
30:13
CLASS: (laughing) BRANDON: And then figures out   every mercenary way to exploit that book  for profit that is legal in our system. 
30:21
CLASS: (laughing) BRANDON: So that you can   let that person back out and they will have  enough, you know, food to eat so that they  
30:26
can go and be artistic the next time. That's  the perspective we'll take in the class. Go.  STUDENT: Should the second person  worry about how the artist feels  
30:35
about what they've done with their baby? BRANDON: Yes. You definitely should. I'm   being a little exaggerating in that. Your artistic  integrity maintains. You are the same person.  
30:44
Right? There are certain things that you will  not do as an artist with your book. And that's,  
30:50
you know--yes, absolutely. Right? I'm just talking  about this idea of the business person shouldn't  
30:56
be in charge when you're writing. But as you  finish the book, learning the business and   letting the business person take charge is a good  idea. But yeah, definitely do not compromise your  
31:07
artistic integrity through revisions because of  what the business person thinks. But sometimes  
31:13
you might. Let me give you an example. John Scalzi wanted to be a novelist.  
31:18
He's a very good writer, good friend of mine. He  had been a blogger for a long time. He decided,  
31:25
"I'm going to be a novelist." So he  went to the bookstore, and he said,   "What's selling right now?" He picked up a few  books and said, "These look like they're selling.  
31:33
I'll write one of these." And then he went home  and then the artist took over and he wrote one   of those. I wouldn't say that John compromised  his artistic integrity, but there definitely was  
31:43
a back and forth between the business person and  the artist when it came to choosing that project.   Right? And how he chose to release it, and sell  it, and things like that. So there definitely--I  
31:55
think there should be communication between the  two sides of your brain. But I do think that  
32:00
letting the artist make the artistic decisions  and letting the business person then learn how   to sell that book rather than to dictate what  the book should be is generally the way you'll  
32:10
want to go. Once in a while that's bad advice.  It might have been bad advice for John. Right? 
32:15
Other questions on what I've  said so far? Yeah, go ahead.  STUDENT: If our first five books  are going to be not so great, should  
32:22
we spend a lot of time revising them? BRANDON: Yes. But here's why. Revision is  
32:29
a difficult skill to learn, on par with learning  to write a book. I learned, while I was not  
32:35
selling books and getting very close, I learned a  lesson that some of my friends who were creating  
32:42
the best artwork were better revisers than they  were writers. And I might, if I were you, like,  
32:50
there's an argument to just putting aside the  first book and then writing the second one   and then coming back later and maybe revising the  first, or maybe not even ever touching the first.  
32:59
But the truth is, a lot of people's second books  are publishable. It might be better if you think  
33:05
you're going to write five and then publish number  two. But most people wish they'd written a couple,  
33:12
even if they are starting off a genius. And revision is a really important thing   to learn. I would say the reason it took me as  long as it did to sell Elantris after I wrote it,  
33:23
because it came out in 2005 and I wrote it in  '98, was because I hadn't learned revision. I  
33:29
would write those first five books, I never did  a second draft. I wrote them and then, you know,   I figured--I'd always--the next book would be  better, so why not just write that. This is a  
33:38
classic--. I'm more of an outliner. This happens  more often to outliners than it does to discovery   writers, that they think, "Well, I'm excited  by the next book. I'm going to go write that." 
33:49
Discovery writers have the opposite problem. They  do tend to over-revise. They write a chapter and  
33:54
then they revise it, and they write a chapter  and then they revise it. And they go back and   revise the first one again. And then they write  Chapter 3, and then they revise the other two.  
34:00
And then now they need to do this, revise  Chapter 3. And then they never get anywhere. 
34:06
Oh, we've got another Nate up  there! Your name isn't Nate, is it?  CLASS: (laughing) BRANDON: Because--this  
34:11
is funny because last year I was telling a story  like this, and I had a guy in my writing group   whose name was Nate who did this. And this  guy's like, "I do that. My name is Nate!" 
34:21
CLASS: (laughing) BRANDON: So this does tend to be   more of a problem. But I will say those writers  who constantly revise the early chapters, they  
34:32
don't tend to make it, has been my experience.  Because having 80 first chapters doesn't get  
34:41
you very far. Now, you could be a fantastic short  story writer. Short stories don't earn any money  
34:46
anymore. So it's really hard to make a living at  short story writing, in fact kind of impossible,   unless you're also doing lecture series  and being a professor. So yeah. So yes,  
34:55
learn revision. It's really important. By  the way, you were in the class before too,   weren't you? Good to see you. All right, we'll  go here and then we'll get some in the back. 
35:02
STUDENT: When you first started writing. BRANDON: Mm hmm.  STUDENT: And you weren't good at it, what was  it, do you think, especially like, when you knew  
35:09
you had to practice and spend free time when  you could be, you know, doing something else,   what was it that got you to go back and write? BRANDON: OK, what made me write? What gave me  
35:18
the motivation? There's a couple of things.  So when I was brand new at this, I saw that  
35:27
if I didn't learn to write I was going to have  to get a job that I did not enjoy as much.  CLASS: (laughing) BRANDON: Because I genuinely enjoyed writing.  
35:35
So I came to BYU as a chemical engineering. CLASS: (laughing) 
35:41
BRANDON: Actually I was bioengineering. But  you know, yeah. Something like that. Because  
35:46
my mother convinced me that engineers got--I was  biochemistry, that's what it was--that engineers  
35:53
got scholarships, and she still wanted a doctor so  badly. And I came to BYU, and they threw me in the  
36:00
weeder classes for chemistry, which I actually  really appreciate because they taught me I did   not want to be doing chemistry every day. Right?  Oh, boy, did I not want to be doing chemistry. I  
36:10
went on a mission to Korea and I'm like, "I'm  on a different continent from chemistry! Oh,   it's so nice!" CLASS: (laughing) 
36:17
BRANDON: But writing, when I would sit down to  write, hours could pass, and I wouldn't know  
36:23
what time it was. That doesn't mean that writing  was easy. Right? Usually starting is hard. Or if  
36:30
I hit a rough patch, you know, I would still  give up or things like that. So I still needed   this motivation. But that was a key sign to me,  that I loved the busy work of writing so much  
36:39
more than other things. So good sign there. And  so the thing that worked best for me is that I  
36:48
would start keeping a spreadsheet with the amount  I'd written each day and my goal, and if I hit my  
36:55
goal then I didn't have to worry about it anymore.  I was making the progress that I need to, and I  
37:00
could go play Halo. Right? I could go do whatever  I wanted because I had hit my goal for the day. 
37:07
And a lot of times I made it such a goal that it  was a little difficult to hit but not impossible.  
37:13
It wasn't actually hard. It was just like I had  to actually work. Most days I would double that   goal. Right? Because it was a goal that--it was  something like 1,000 words. Right? Enough that I  
37:24
actually had to sit down and do it, but once  I got into it I would keep going. And then I  
37:32
put that on my spreadsheet, and I watched those  numbers counting up. And it worked for me like   the progress bar in an MMO for getting your next  level worked. I'm like, "Hey, I will hit 25% soon.  
Survivorship Bias
37:45
Wow! I will hit 50%! I'm almost done!" And that  every day was a balance of making me feel like,  
37:53
"Man, I've got my work done. I can relax. I don't  have to stress about this." My job right now isn't  
37:58
to publish books. My job is to write those first  five books and to learn from them, so if I today  
38:05
have hit my 1,000 words, I'm on my path. I've done  basically all that I can do realistically with my,  
38:12
you know, a normal person's mental health and  things like that, in order to hit that goal   in 10 years. And it worked. Granted--I'm  going to get to your question up here. 
38:23
Let's talk about survivorship bias. We're  recording this this year, so I think every person  
38:29
entering into a creative or even a professional  field needs to know about survivorship bias.  
38:35
Because there are a whole lot of grifters out  there who coast on survivorship bias. Survivorship  
38:40
bias is our brains are more likely to weigh the  words of someone who's been successful, even if  
38:49
their success was random, than someone who has  not been. If we didn't know that flipping coins  
38:55
was random, and we had a competition and everyone  in here flipped coins until we had one person left   that had flipped heads the whole time, everyone  in this room would be asking them for advice next  
39:05
time. And indeed, they may go on the guru circuit,  earning big money writing books about flipping  
39:11
coins and about how you do it and their process.  And they might even name it and come up with a  
39:16
YouTube course that you can pay for. Right? CLASS: (laughing)  BRANDON: That's survivorship bias. We cannot  say whether what contributed to my success.  
39:27
This is why I try to give you lots of tools.  Right? That worked for me. I am a survivor  
39:32
of that system working. Who knows? Right? But  that's the best I can give you. So I like the  
39:38
way you phrased your question. What, for me,  kept me going? And that's what kept me going.  Now, something else you need  to hear about. What time is it? 
39:47
RACHEL: It's 7:46. BRANDON: 7:46. We go to 8:30?  RACHEL: 8:15. BRANDON: 8:15. OK. All   right. I've got time left. STUDENT: [inaudible] 
39:53
BRANDON: Yeah. CLASS: (laughing)  BRANDON: Yeah, I've got another class. But  we've gotten through almost all of this.  
39:58
So I can do lots of questions. Let's tell you the story of Brandon  
40:04
almost giving up. Some of you have heard this  story before. I am, in this story, applying to  
40:12
grad schools and getting rejected from all of  them. NYU, rejected. Columbia, rejected. Iowa,  
40:21
rejected. Everybody rejected me. I had written, at  the time, around 12 novels, and I hadn't sold any.  
40:33
My father would call me and give me father-speak  for "I am very concerned" by saying, "Son,  
40:39
your mother's very concerned." CLASS: (laughing)  BRANDON: That's father-speak. A little  interpretation for you if you ever get  
40:45
that. They were worried, both of them, that I was  going to end up begging for beans on the side of  
40:52
the road because instead of becoming a doctor  I had decided to be a science fiction novelist.  
40:59
And they were kind of right. Right? Like, I talked  about it earlier. Having a backup plan is a good  
41:05
idea in a career where one out of 20 talented  people who work very hard for 10 years are  
41:13
going to make a living. Right? Nineteen of them  won't. And Janci will tell you that it took her,  
41:20
even after she started selling books, over a  decade to start earning what people would consider  
41:26
even close to a livable income. right? I think  the first year that she made--she said she made  
41:33
enough to live on by itself with her writing  was the year she co-authored a book with me. 
41:39
CLASS: (laughing) BRANDON: And she is very good at self-publishing.   She knows her stuff. So it's good to have a  backup plan. Right? And I didn't have one. I  
41:52
had decided to--eventually I got into BYU's grad  program. Right? I did get into BYU. Everyone else  
41:58
rejected me. I went through one round of all the  top schools. They all rejected me. Then I went to   the second-tier schools and BYU, and of them, only  BYU let me in for grad school. You don't usually  
42:07
want to go to grad school in the same place that  you went to undergrad, which is why I applied   everywhere else first. But I was only applying to  the schools that if I got a degree from I could  
42:18
then go on to get a job, you know, as a writer.  Because BYU, at the time, didn't have an MFA. 
42:25
An MFA was considered the degree you needed to  be a professional teacher in creative writing.  
42:31
Getting a master's from BYU in creative writing  actually--my parents didn't know it--at that point  
42:36
would not do anything for me becoming a professor.  It was virtually useless as a step to being a  
42:44
professor because it wasn't an MFA, wasn't  a Master of Fine Arts. They now have one,   and their program has gained reputation because  of that. So those who are in it now, don't panic.  
42:56
But back then it really couldn't do anything. That  said, Andi was in my class, and she's a professor  
43:02
at BYU right now, and she's really good. I don't  think she got an MFA though, did she? Or did she   go back and get one? She was in my class when it  wasn't--. We didn't get the F. We just had an MA. 
43:13
CLASS: (laughing) BRANDON: So I got into BYU. But my parents are   calling me and I'm like, "Oh, man. I'm stalling.  What am I doing with my life? I can't teach." I  
43:24
went to class the first day in university as a  creative writing major, and Lance was teaching  
43:31
the class. Anyone here--did Lance retire? Does  anyone know if Lance retired? Lance Larson? 
43:36
STUDENT: He's still here. BRANDON: He's still here. You   said he retired! You're wrong! CLASS: (laughing)  BRANDON: Ha ha. RACHEL: OK. Sorry. 
43:43
CLASS: (laughing) BRANDON: Lance was the poet   laureate of Utah. He's a very good teacher, very  good poet. He was in charge of graduate students  
43:51
in the master's program in creative writing, or in  just the Masters of English program. And he got up   on the first day of kind of your, "Here you're a  grad student now. Let's talk about it," and said,  
44:00
he pulled out a thing and said, "Here is the CV,"  which is kind of like the resume for students for   those online who might not know, "of someone who  got into a top tier school for a Ph.D. and went  
44:09
on and became a professor in English." And it went  to the floor. Right? He said, "They were on every  
44:14
journal. They worked with this many professors on  these. And they spent something like 40 hours a  
44:21
week outside of school working in order to build  their CV so that they could get into a top school  
44:27
so that that school could then propel them  into a career. That's what you're going to   need to do if you want to become a professor  at a prestigious university on a tenure track." 
44:38
And I looked at that and I said, "I cannot write  books and do that. So I'm not going to do that."  
44:46
And I didn't. But I didn't have a backup.  Right? And I kind of had to, at that moment,  
44:55
confront "What do I do?" Right? Do I give up? Do  I go get a real job? I was working at a hotel,  
45:02
a graveyard shift, so I could write at work.  Right? Overnight. Worked very well for me.   It was bad advice for Isaac, who tried to do  that, a friend of mine who's now at my company.  
45:12
He tried to do the same thing, and he is not  a night person, and it did not work for him.  CLASS: (laughing) BRANDON: So I looked at this and I thought, "Am  
45:22
I going to stop writing?" And looking seriously  and honestly at my heart, I said, "No. Whatever I  
45:30
end up doing, I'm not going to stop writing. This  is who I am. I'm going to keep writing. And if  
45:35
I'm age 90 and I never sell a book, and my books  are only for my family and my friends, then I'm a  
45:46
success. That's the success I can control, and I'm  going to do that." Now I'd been doing everything I  
45:52
was supposed to do. I'd been submitting. But  people--this was when George first got big,   and grimdark was the new hotness. Right? Brandon  is not grimdark. I tried. It was not--. I tried  
46:06
writing grimdark and it turned into the story  of a grimdark assassin who found hope and love. 
46:13
CLASS: (laughing) BRANDON: I'm not even kidding. Right? Like,   just grimdark is not my thing. And so, you know,  darkness in a world, great. But not my thing. So  
46:27
I'm like, "I can't--" you know. And so I sat  down and said, "Well, they keep telling me,   the publishers keep telling me I'm writing books  too long." They wanted shorter books. What they  
46:36
were really hunting, those of you who know your  fantasy history, they wanted George's aesthetic,   but they wanted it to be cheaper to publish.  Right? The bigger the book--you can't--. 
46:45
So here's some economics of books for you. A  400,000-word book, which is the length of the  
46:51
Stormlight books, and the Game of Thrones  is even longer sometimes. Right? That is  
46:57
four times more expensive to edit, four times  more expensive to--well, maybe not four times,  
47:06
but significantly more expensive to print,  significantly more expensive to ship,   and to the bookstores, it's four times of the  100,000-word book, more expensive to put on the  
47:17
shelf. Because if you can put three books on  the shelf or one book, which one do you want   to put on the shelf? Right? The problem is the  way that economics of entertainment work in our  
47:27
world is you don't charge much more for longer  entertainment. movies cost about the same no   matter what length they are. Books maybe go up  a buck. But a Stormlight book should probably,  
47:38
like if a normal paperback is $8, a Stormlight  book in paperback should, for the amount of, like,  
47:44
money and time and all of these things, should  probably cost, like, $25. But we can't do that. 
47:49
And so they don't like long books.  They're better with them now that   eBooks are a thing. But audiobooks still,  you know, more expensive to produce. Anyway,  
47:58
they wanted Joe Abercrombie. They wanted George,  like grimdark aesthetic but short. And I was  
48:05
like the worst for them then. Right? I was long,  and I was, like, hopeful epic aesthetic. Right? 
48:11
CLASS: (laughing) BRANDON: The big hotness was low magic,   and I was like, "There's 30 magic systems." Right? CLASS: (laughing) 
48:19
BRANDON: And this is the era when people  didn't even use the word magic system the   same way they do now. They didn't know what to do  with me. And so I got all these reactions. Like,  
48:29
I remember walking up to someone who rejected me  and I'm like, "Thank you for the rejection. Do   you have any advice?" It was a form rejection.  He said, "Read the first chapter of Game of  
48:37
Thrones and write something like that." Steve  Saffel at Del Rey. That's exactly what he told  
48:43
me. And so it's like, whatever. So I'm like,  "All right. I'm going to write what I want. I'm  
48:51
not going to care. They tell me to write short.  I'm going to write the biggest darn book." Right?  CLASS: (laughing) BRANDON: They tell me low  
48:58
magic. No, no, no! Right? CLASS: (laughing)  BRANDON: And I wrote The Way of Kings. The Way of  Kings Prime. Right? And as I was finishing that  
49:06
book is when Elantris sold. And I still remember  that kind of, you know, that belly of the whale,  
49:13
if you want to use your writing metaphors,  that long, dark tea time of the soul. 
49:18
STUDENT: (laughing) BRANDON: Dirk Gently. Douglas   Adams quote there. That moment was really, really  helpful for me because I had gone through making  
Writing in the Same World
49:28
the hard decision that I was going to write for  the rest of my life before I became one of the  
49:34
most famous writers in the world. And that was  really handy to have made that decision before I  
49:40
sold and things like that. Tangents, I warned you  about those. We got time left? All right. Question  
49:46
back there. Hit me. I'm going to do a rapid  fire round. I'm going to actually do them fast. 
49:51
STUDENT: If you're too attached to  a world you built and don't want to,  
49:56
like, go to the effort to jump ship and worldbuild  a new thing and plan all these new things.  BRANDON: Yeah. STUDENT: Would you say it's detrimental,  
50:02
or is it fine to still write, like, five books  but in the same setting or the same world?  BRANDON: I think that's good. That's great.  Totally worth doing. The question is, let's  
50:11
say you want to write five books, but you don't  want to abandon all your worldbuilding. Totally  
50:17
OK to write those all in the same world. Now what  I would tell you is there's a gambit for you here.   All right? You can do a Sanderson, and you can  write five different books with five different  
50:28
protagonists, just you can share some of the  worldbuilding. It's more like an Anne McCaffrey.   She used to do this and things like that. Or you  can do a Temeraire. Temeraire, she wrote four of  
50:39
those, I think, maybe three, four, straight in  a series. Those were her, you know, she just  
50:44
wrote those books without selling any of them. Now why this is a gambit is, you cannot send Book  
50:49
2 of a series to an editor, or sell it to indie  publishing, until you've, you know, like, if they  
50:56
reject Book 1, you can't send them Book 2. But  if they're the same world, you can. But if it's   a sequel, you can't. She put all her eggs in  the same basket but then when Temeraire sold,  
51:06
the publishers knew they had gold on their hands  because they had three finished books and maybe   a fourth. So they put just an enormous marketing  campaign behind that. You won't understand how big  
51:15
a deal this is because you're all young, but some  of you will who are not, you know, quite so young.  
51:23
Her cover blurbs on her first three books were  Stephen King, Anne McCaffrey, and Terry Brooks. 
51:31
CLASS: (oohing) BRANDON: They sent all of them all three books and   they're like, "All three are done? Well, I'm going  to read them." Right? And they cover blurbed them.  
51:37
It was amazing. And then she stomped me at the  Hugo Awards for best new author because of that,  
51:45
and she deserved it. CLASS: (laughing)  BRANDON: So anyway, there's your gambit.  Writing all in the same world but not direct  
51:52
sequels is kind of the best of both. So if  that appeals to you, totally do that. It's   what Rachel did. It worked for her. STUDENT: So I was wondering, like,  
52:01
if you have a world that you're, like, incredibly  proud of and you've been working on for years.  BRANDON: Yeah. Uh huh. STUDENT: How do you escape,  
52:07
like, the fact of, like, using the first,  like, four or five books to, like, throw   away those so you can get to that sixth one? BRANDON: OK. So you've got a world you've been  
52:14
working on. You're so excited by. You don't  want to throw it away because it's your baby.  
52:20
You got a couple of options. Number one is, write  that first book, get it out of your system. Know   that you're probably just going to then come back  and write it better. OK? That's the one I kind of  
52:30
recommend. Way of Kings Prime didn't sell. There  was stuff wrong with it. Years later when I had  
52:36
more experience I just wrote it up from scratch.  And kind of having a book that was a rough draft  
52:42
of the book I wanted to write, where I could  see all the flaws with my now experience and   write a much better version--I didn't revise  it, I just started on page 1--but it's almost  
52:49
like I had an outline that was the wrong version  of the book. It was really handy. And it is part  
52:55
of why Way of Kings is so strong as a series, is  because I know stuff about that world I don't know   about others because I wrote a whole book that I  threw away. Right? So that's what you can do. But  
53:04
another thing people do is they just--ideas  are cheap. This is what you will learn as a  
53:09
writer. The ability to take ideas and make them  great--and you're going to be my last question,  
53:15
so I'll get to you. The ability to take ideas and  make them great is what people are looking for. 
53:21
Two stories for you. Maybe one.  We'll see how much time I have.  RACHEL: 8:15. BRANDON: There is a writer who, he was  
53:35
hanging out on some forums and he was arguing with  some people, and he took this stance. He was a new  
53:43
writer, unpublished. And he said, "I think ideas  are cheap." And the other person's like, "No,  
53:48
no, no. Ideas are what make science fiction and  fantasy. If you don't have good ideas then you've   got nothing." And the first writer's like, "I tell  you what. Give me your three worst ideas." Or your  
53:59
two worst ideas. It was two, I think. I asked  him this at dinner, and it's true. So I'd heard   it apocryphally before. But he confirmed it to me.  You can ask him in person. He said, "Give me your  
54:07
two worst ideas." They said, "All right. Pokémon  meets the lost Roman legion." And Jim Butcher  
54:18
took that, and he wrote a book series called Codex  Alera. I heard it over here. They're fantastic. In  
54:23
the hands of a great writer, great being someone  who's practiced a bunch, you can take basically  
54:29
any idea, and you can make gold from it. A writer with good ideas but not the skill,  
54:35
it's like playing piano. That's my other thing.  We've mentioned playing piano. The other story is,   if we had someone come up here who'd been  practicing piano for a few months and someone  
54:44
who had been practicing for 20 years, how long  do you think it would take you to tell which is   which. Very short amount of time. Right? It's  the same thing in writing. Editors, readers,  
54:56
they can tell if you've put that time into it. So ideas are cheap. Find some idea that just,  
55:02
you know, a writing prompt. Mash it together  with another idea and add the plot line of a  
55:08
film that you love that's in a different genre  and just write that book. Right? You'll be like,  
55:14
"I'm going to write The Godfather. I love the  Godfather. Except it's mice, and, you know,  
55:21
the magic system is magic cheese." CLASS: (laughing)  BRANDON: Right? And I'm going to write that  book, and then that gives you your practice,  
55:28
and you will then discover that ideas kind of are  cheap. And you'll get some practice in. And then   you save that book until later on. Either of those  are perfectly viable. All right? Last question. 
55:39
STUDENT: How do you make yourself get  to the point of, like, just rewriting a  
55:45
story? Because I've written some-- BRANDON: Yeah. How do you force   yourself to rewrite? STUDENT: --novels but,   like, they need rewrites, but I don't  know how to make myself do that. 
55:54
BRANDON: So, good question. How do you make  yourself revise? I am there with you. I hate   revision. It's my least favorite part of  everything, the whole process. And that's  
56:02
why it took me so long. I am really good at  revision. People hear this and they assume I'm   bad at it. The things that you're bad at,  that you have to force yourself to learn,  
56:10
or you will not be able to succeed professionally,  tend to end up as your strengths. That won't help  
56:15
you because blah, blah, blah. My weaknesses  become strengths. Yeah. I know. That's hard,   and I don't want to do it. Right? CLASS: (laughing) 
56:22
STUDENT: It's like a mental burnout. BRANDON: Yeah. Yeah. So watch--you  
56:27
need to--. Well, helpful for this is learning  your--whether you respond to carrots, or sticks,  
56:36
or something else. What makes you consistently do  the things you want to have done? Right? There's  
56:42
probably other things in your life you want to  have done that you are able to get yourself to do,   whether it's get up in the morning, whether it's  go to the gym, whether it's read scriptures.  
56:52
Whatever it is, what do you have that you have  built a habit out of already? And number one,  
56:58
what made you do that? And number two, can you  bundle your habits? If there's something you  
57:03
already do every day, you're like, "Every day  I go and I get my favorite dirty cola from the  
57:11
random dirty cola place that also sells cookies,  because why not all the diabetes in one place?" 
57:19
CLASS: (laughing) BRANDON: "And I know I do that on the way home   from school. I am going to stop in that shop, and  I am going to revise for only 30 minutes. And then  
57:27
when I get home, I get to do something else that  I find fun." Well that, that's what we call kind   of bundling, when you group something you don't  want to do with something you've already built  
57:36
a habit to do so that the thing you don't want  to do but you want to have done also becomes a   habit. That works very well. Learning whether you  respond to, you know, like for me, counting up,  
57:47
I can see the percentages, and small bites. Or whether--some people binge. Right? Like,  
57:54
"I don't like revision, so I'm going to take  this week that I'm off of school in the summer,  
57:59
and I only revise. I don't get to go do anything  else. I do it for 12 hours a day. Then I collapse.  
58:05
And then at the end of the week I'm done, and I  get to take the summer off. And then I'll start   writing a new book when Fall semester starts." You  have--like, your job as a new writer is to figure  
58:17
out what triggers these things and makes them  work in your mind. Helpful for me is to make a  
58:22
revision guide. If you're an outliner naturally,  which you might be if you don't like revision,   having an outline for your revision that has  targeted goals, kind of like--have you ever done  
58:31
any programming, computer programming? STUDENT: A tiny, tiny bit.  BRANDON: OK. In programming you might have a  bug list, starting with your most important  
58:39
bugs. You're like, "In this book, I've gotten  feedback this character doesn't work. Here's  
58:46
a plan for fixing the character. It's my most  important thing. The main goal in this revision   is to fix that character. If I have room in my  brain for a second goal, here's the second most  
58:55
important thing. And I'm going to find three  places to foreshadow this or to add a scene  
59:01
that fixes this problem." And then you do a  revision, checking things off that list so   you feel like you're making accomplishments, and  you're basically killing bugs in your bug report.  
59:10
That does tend to work for some people as well,  particularly if they are naturally an outliner,  
59:15
having an outline. But to do that, you need to  get feedback. And to get feedback, we're going   to talk about writing groups. STUDENT: Segue! 
59:21
BRANDON: Segue. STUDENT: Yay! 
59:26
CLASS: (applause) BRANDON: Welcome. So segue. By the way,  
59:33
I used to think that you spell--that S-E-G-U-E,  anyone else have that, was short for segue,  
59:42
and there was actually a word that was that plus  WAY that was segue, and that the shortened version   was seg, and you'd just say seg, or people would  just write it. Right? Did anyone else have this? 
59:53
STUDENTS: Yes. BRANDON: Like, why does that word say segue?   French! French! Oh, you Normans. You Normans  came in. You took our nice Germanic language  
1:00:04
that liked to crunch and kill and eat, and  you made it instead so that we, you know,  
Writing Groups
1:00:09
that we had rendezvous. CLASS: (laughing)  BRANDON: And we didn't give up. We surrendered.  And now we have two words for everything,  
1:00:17
one Latinate and one Germanic. It's actually  really good for writers because the Latinate   words naturally sound very upscale to us. And if  you can learn to watch for the Germanic words,  
1:00:28
because those were the lower level words back in  middle English era, and the Norman/Latin words  
1:00:36
were the high class. And that's still  around in our language. So if you say,  
1:00:42
"I surrender" that indicates education. If you  say, "I give up" that indicates lower class.   You can use that as a writer so it's actually a  useful thing. So it's good. But it is annoying. 
1:00:51
All right. Writing groups. Writing groups.  Writing groups aren't for everyone. OK? In fact,  
1:00:58
writing groups can ruin your book. Learning  to take feedback is important for the majority  
1:01:05
of writers. Writing groups are one of the ways  that we can do that. And I am able, in my class,  
1:01:12
to do it in a controlled situation where it will  not ruin people's books. I put a TA in every  
1:01:19
writing group, and the TA knows how to make sure  that no one ruins each other's books. It is a good  
1:01:26
tool to try. Part of this is, part of the reason  for this is, when I took this class in 1999,  
1:01:35
I formed a writing group with four people:  me, Dan Wells, Peter Ahlstrom, and Ben. 
1:01:45
CLASS: (laughing) BRANDON: Dan and I went on to become   pros. He sold, like, he found an editor, I sold  to that editor, and then he sold to that editor,  
1:01:51
and we both went full time. Peter became  a full-time editor at Tokyopop, and then I   hired him to be my Editorial VP at Dragonsteel.  All three of us went on to become pros, and we  
1:02:02
are three of the four people from that class  who went on to be pros. Now, part of that was  
1:02:10
because I was in this class and we were reading  writing samples, and I zeroed in on Dan and said,   "He's a good writer. I'm going to put him in a  writing group with me." And he said, "My friend  
1:02:19
Ben wants to join." I'm like, "Sure." Ben's a CS  guy. He's our friend. He doesn't really write.  
1:02:26
But we make fun of him on my podcast. CLASS: (laughing)  BRANDON: And then Peter was at the magazine  with us, and I knew that Peter had a really good  
1:02:35
editorial eye. And I'm like, "I'm going to put  him in the writing group because he's an editor   and he knows what he's doing." So I specifically  picked out the two people in the class that I  
1:02:46
thought were most likely to make it, and I formed  a writing group with them, and I was really good   at that, apparently, of picking them out. Right?  But another reason is, for the same reason that  
1:02:57
Tolkien and Lewis were in the same writing group.  Right? Success breeds success. Writing groups from  
1:03:04
my class that stick together often do give each  other help and legs up and things like that. 
1:03:12
So while writing groups aren't for everyone,  I do think they're worth trying. So I'm going  
1:03:18
to give you today the best inoculation against  writing groups ruining your writing so that you  
1:03:26
can try them out if you would like. And then after  this class, if you would like you to split you in  
1:03:31
this group into writing groups, I will do so. All  right? If you don't want to be in a writing group,  
1:03:38
then you can leave and you can laugh at  us all with your other cool writing group   with cooler friends. CLASS: (laughing) 
1:03:46
BRANDON: So here's a couple of simple rules  that if you follow will help a ton. Number one,  
1:03:53
if you are a discovery writer, be very careful  about taking any advice for your book until after  
1:04:03
you have finished said book and are working on  a different one. This is because people who tend  
1:04:10
to discover their story can be taken over by the  whims of other people giving feedback too early.  
1:04:18
And Stephen King is the quintessential discovery  writer. One of the reasons he doesn't like writing  
1:04:24
groups, which he doesn't, is because they will  do this to him. One of the reasons he doesn't   like outlines is because if he writes an outline  he feels like he's already discovered the book,  
1:04:31
and his enthusiasm and excitement for  that book vanishes. Both perfectly   valid ways to be a writer. This is why it's  important to understand these things. Right? 
1:04:40
So if you are a discovery writer, try  not to submit too early, or if you do,  
1:04:49
be aware of what can happen if someone hijacks  your book. I had someone in a writing group  
1:04:54
once come and submit a chapter and we gave some  feedback. And they submitted another chapter,   and it was wildly different, but it was in the  same book. And the third chapter was wildly  
1:05:01
different. And we're like, "So you were writing a  romance, and now there's vampires." And she said,  
1:05:07
"Yeah, I took a class at BYU, and the  people in the class said, "You know,   vampires would be really good in this, and they're  selling really well right now, so I added them to  
1:05:16
the book." And the next one they're like, oh,  it's not exciting enough. You know, thrillers   are doing really well because The DaVinci Code  had just come out. And she was like, "Well,  
1:05:25
maybe I should make this a thriller." And her book  was a different book in every chapter. Writing  
1:05:30
groups can do that to you. OK? Now you're warned  about it. Hopefully, that will inoculate you. 
1:05:36
Number two, if you are getting feedback, try  not to say anything. This is really hard. Your  
1:05:44
job getting feedback is to be a fly on the wall  while people are talking about a story and write  
1:05:52
down what they say. In Hollywood they do this cool  thing where for years they would bring people in  
1:05:58
and they would show them a pilot for a new sitcom  and tell them, you know, 'We're going to ask you  
1:06:04
what you thought of it afterward." And people  would watch it. And then afterward they would say,   "All right. Now there was a commercial at break  number one. What brand was this commercial for?"  
1:06:17
Because they didn't want people to actually  be paying attention to the commercials, just   to the thing. And they'd use the same sitcom for  years because it was just to test the commercials.  
1:06:26
Because they didn't want people to be too aware. You want to be like that. You don't want your  
1:06:32
audience, who is your writing group, to be aware  of what you're planning to do. And if you defend  
1:06:38
yourself, if you ask too many questions, you will  predispose them, and you will not get authentic  
1:06:44
feedback. The best thing you can do is stay quiet.  Now, you are going to ask questions now and then.  
1:06:50
Try not to ask too many questions, trying to  just write down the feedback and use it later.  
1:06:56
And this is, you know, later is important. Most  new writers I recommend taking feedback on a book  
1:07:02
you've finished while you're writing something  else and then coming back to that feedback   months later when you're in revision mindset,  reading through it all, making a revision guide. 
1:07:13
Usually I throw out--I take maybe a third of the  feedback that I'm given. And I have a really good  
1:07:21
writing group. So you're not going to take most of  it, but there's going to be a lot in there that's   going to help you build this revision guide. Then  you're going to revise your book. And then you're  
1:07:29
going to find a new audience and see if you  fixed the things that you thought you fixed.  
1:07:35
This will be really good for you as a new writer  learning to target people. So write it down.  If you are giving feedback, last  point of advice, be descriptive,  
1:07:45
not proscriptive. Did you say it before I got to  it? You're cheating. You took the class before. 
1:07:50
CLASS: (laughing) BRANDON: You want to describe the piece's   impact on you through words, emotion words,  not try to fix their book. Your job isn't to  
1:08:01
fix their book. Editors fix books. Beta readers,  writing groups, just are a test audience so that  
1:08:08
the author can tell what people are authentically  feeling as they read the book. So you just say,   "I really enjoyed this. I really enjoyed this.  This part was confusing. I wasn't emotionally  
1:08:20
connecting right here. I lost blocking right  here." Not, as Janci got, "You should add  
1:08:27
rats with swords to this scene." Ask her about  that if she comes and teaches the class ever.
    """
    print(f"Original: {raw_input}\n")
    
    # regex_only = cleaner.clean_regex(raw_input)
    # print(f"Regex Only: {regex_only}\n")
    
    final_output = cleaner.clean_text(raw_input)
    print(f"Final Output: {final_output[:500]}...") # Print preview

    output_file = "cleaned_output.txt"
    with open(output_file, "w") as f:
        f.write(final_output)
    print(f"\nFull cleaned text saved to {output_file}")
